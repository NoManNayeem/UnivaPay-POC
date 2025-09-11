'use client';

import Script from 'next/script';
import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';

// Constants (consider moving these to environment variables)
const RETURN_URL = 'https://example.com/';
const API_URL = 'http://127.0.0.1:8000';
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzU3OTUxMDY5LCJpYXQiOjE3NTc1MTkwNjksImp0aSI6IjA5YzBmY2RmNmNkZjRlNmFhYjNlOWJjM2EzYzMyMjdkIiwidXNlcl9pZCI6MX0.vCVluiHHObqUVH-v6nVtvsqwPlmirOKyHQm6YnwCUqA';

export default function PaymentPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState('one-time');
  const [itemName, setItemName] = useState('');
  const [amount, setAmount] = useState('');
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState({ type: '', text: '' });
  const [appConfig, setAppConfig] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    
    // Fetch widget configuration from backend
    const fetchConfig = async () => {
      try {
        const response = await fetch(`${API_URL}/payment/widget-config/`, {
          headers: {
            'Authorization': `Bearer ${TOKEN}`,
          },
        });
        
        if (response.ok) {
          const config = await response.json();
          setAppConfig(config);
        } else {
          console.error('Failed to fetch widget config');
        }
      } catch (error) {
        console.error('Error fetching widget config:', error);
      }
    };
    
    fetchConfig();
    
    return () => { mountedRef.current = false; };
  }, []);

  const setError = (t) => setMsg({ type: 'error', text: t });
  const setSuccess = (t) => setMsg({ type: 'success', text: t });

  // Create transaction token first, then use it for payment
  const createTransactionToken = useCallback(async (token, paymentData, isSubscription = false) => {
    try {
      console.log('Storing transaction token with data:', token);
      
      // First store the transaction token using the correct endpoint
      const tokenResponse = await fetch(`${API_URL}/payment/transaction-tokens/store_token/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${TOKEN}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(token)  // Send the raw token object
      });
      
      console.log('Token storage response status:', tokenResponse.status);
      
      const tokenResult = await tokenResponse.json();
      console.log('Token storage response data:', tokenResult);
      
      if (!tokenResponse.ok) {
        throw new Error(tokenResult.detail || tokenResult.error || 'Failed to store transaction token');
      }
      
      const tokenId = token.id;
      console.log('Using token ID:', tokenId);
      
      // Now use the token to create payment
      const paymentEndpoint = isSubscription 
        ? `${API_URL}/payment/univapay/subscription/` 
        : `${API_URL}/payment/univapay/charge/`;
      
      console.log('Creating payment with data:', {
        ...paymentData,
        transaction_token_id: tokenId
      });
        
      const paymentResponse = await fetch(paymentEndpoint, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${TOKEN}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          ...paymentData,
          transaction_token_id: tokenId
        })
      });
      
      console.log('Payment creation response status:', paymentResponse.status);
      
      const paymentResult = await paymentResponse.json();
      console.log('Payment creation response data:', paymentResult);
      
      if (!paymentResponse.ok) {
        throw new Error(paymentResult.detail || paymentResult.error || 'Payment failed');
      }
      
      // Check for redirect (3DS)
      const redirectInfo = paymentResult?.univapay?.redirect;
      if (redirectInfo?.endpoint) {
        console.log('Redirect required to:', redirectInfo.endpoint);
        window.location.href = redirectInfo.endpoint;
        return;
      }
      
      return paymentResult;
    } catch (err) {
      console.error('Error in createTransactionToken:', err);
      throw new Error(err.message || 'Payment processing failed');
    }
  }, []);

  // One-time payment handler
  const handleOneTimePayment = useCallback(async () => {
    setMsg({ type: '', text: '' });

    const amt = Number(amount);
    if (!itemName.trim()) return setError('Item name is required.');
    if (!Number.isInteger(amt) || amt <= 0) return setError('Amount must be a positive integer (JPY).');

    if (!appConfig?.app_token) return setError('Missing app token configuration');
    if (typeof window === 'undefined' || !window.UnivapayCheckout) {
      return setError('UnivaPay widget is not ready yet.');
    }

    setLoading(true);
    try {
      console.log('Opening UnivaPay widget for one-time payment');
      
      const checkout = window.UnivapayCheckout.create({
        appId: appConfig.app_token,
        checkout: 'payment', // token or payment
        tokenType: 'one_time',
        cvvAuthorize: true,
        redirect: RETURN_URL || undefined,
        paymentMethods: ['card'],
        
        amount: amt,
        currency: 'JPY',

        onTokenCreated: async (token) => {
          try {
            console.log('Token created:', token);
            
            // Prepare payment data
            const paymentPayload = {
              amount: amt,
              currency: 'JPY',
              metadata: { item_name: itemName.trim() },
              redirect: RETURN_URL ? { endpoint: RETURN_URL } : undefined
            };

            const result = await createTransactionToken(token, paymentPayload, false);
            
            if (mountedRef.current) {
              setSuccess(`Payment submitted. Status: ${result?.univapay?.status || 'unknown'}`);
              setItemName('');
              setAmount('');
            }
          } catch (err) {
            console.error('Error in onTokenCreated:', err);
            if (mountedRef.current) {
              setError(err.message || 'Failed to process payment');
            }
          } finally {
            if (mountedRef.current) setLoading(false);
          }
        },

        onClose: () => {
          console.log('Widget closed');
          if (mountedRef.current && loading) setLoading(false);
        },

        onError: (err) => {
          console.error('Widget error:', err);
          if (mountedRef.current) {
            setError(typeof err === 'string' ? err : (err?.message || 'Widget error'));
            setLoading(false);
          }
        },
      });

      checkout.open();
    } catch (err) {
      console.error('Error opening widget:', err);
      if (mountedRef.current) {
        setError(err?.message || 'Failed to open UnivaPay widget');
        setLoading(false);
      }
    }
  }, [amount, itemName, createTransactionToken, appConfig]);

  // Subscription handler
  const handleSubscription = useCallback(async (plan) => {
    if (loading) return;
    if (!appConfig?.app_token) { setError('Missing app token configuration'); return; }
    if (typeof window === 'undefined' || !window.UnivapayCheckout) {
      setError('UnivaPay widget is not ready yet.');
      return;
    }

    const periodMap = { 
      monthly: 'monthly', 
      '6months': 'semiannually' 
    };
    const amountMap = {
      monthly: 10000,
      '6months': 58000
    };
    
    const period = periodMap[plan];
    const planAmount = amountMap[plan];
    
    if (!period) { setError('Invalid plan'); return; }

    setMsg({ type: '', text: '' });
    setLoading(true);

    try {
      console.log('Opening UnivaPay widget for subscription:', plan);
      
      const checkout = window.UnivapayCheckout.create({
        appId: appConfig.app_token,
        checkout: 'token',
        tokenType: 'subscription',
        subscriptionPeriod: period,
        redirect: RETURN_URL || undefined,

        onTokenCreated: async (token) => {
          try {
            console.log('Token created:', token);
            
            // Prepare subscription data
            const subscriptionPayload = {
              amount: planAmount,
              currency: 'JPY',
              period: period,
              metadata: { plan: plan },
              redirect: RETURN_URL ? { endpoint: RETURN_URL } : undefined
            };

            const result = await createTransactionToken(token, subscriptionPayload, true);
            
            if (!mountedRef.current) return;
            
            const nextStatus = result?.univapay?.status || 'unknown';
            const subId = result?.univapay?.subscription_id || '—';
            
            setSuccess(`Subscription created (id: ${subId}). Status: ${nextStatus}`);
          } catch (err) {
            console.error('Error in onTokenCreated (subscription):', err);
            if (!mountedRef.current) return;
            setError(err.message || 'Failed to create subscription');
          } finally {
            if (mountedRef.current) setLoading(false);
          }
        },

        onClose: () => {
          console.log('Widget closed');
          if (mountedRef.current && loading) setLoading(false);
        },

        onError: (err) => {
          console.error('Widget error (subscription):', err);
          if (!mountedRef.current) return;
          setError(typeof err === 'string' ? err : (err?.message || 'Widget error'));
          setLoading(false);
        },
      });

      checkout.open();
    } catch (err) {
      console.error('Error opening widget (subscription):', err);
      if (mountedRef.current) {
        setError(err?.message || 'Failed to open UnivaPay widget');
        setLoading(false);
      }
    }
  }, [loading, createTransactionToken, appConfig]);

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      <Script
        src="https://widget.univapay.com/client/checkout.js"
        strategy="afterInteractive"
        onLoad={() => {
          console.log('UnivaPay script loaded');
          setReady(true);
        }}
        onError={() => {
          console.error('Failed to load UnivaPay script');
          setError('Failed to load payment widget');
        }}
      />

      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-md">
        <div className="flex border-b border-gray-200 mb-4">
          <button
            className={`py-2 px-4 font-medium text-sm ${activeTab === 'one-time' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500'}`}
            onClick={() => setActiveTab('one-time')}
          >
            Buy Products
          </button>
          <button
            className={`py-2 px-4 font-medium text-sm ${activeTab === 'subscription' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-500'}`}
            onClick={() => setActiveTab('subscription')}
          >
            Subscribe
          </button>
        </div>

        <h1 className="text-xl font-semibold">
          {activeTab === 'one-time' ? 'Buy Products' : 'Subscribe to a Plan'}
        </h1>
        
        <p className="text-sm text-gray-600 mt-1">
          {activeTab === 'one-time' 
            ? 'Enter an item and amount, then pay via UnivaPay.' 
            : 'Choose a plan. A secure UnivaPay popup will collect your card and create a subscription token.'}
        </p>

        {!appConfig?.app_token && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Loading payment configuration...
          </div>
        )}

        {msg.text && (
          <div className={`mt-4 rounded-md border p-3 text-sm ${msg.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-green-200 bg-green-50 text-green-700'}`}>
            {msg.text}
          </div>
        )}

        {activeTab === 'one-time' ? (
          <div className="mt-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Item name</label>
              <input
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                value={itemName}
                onChange={(e) => setItemName(e.target.value)}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Amount (JPY)</label>
              <input
                type="number"
                inputMode="numeric"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                min="1"
                step="1"
              />
            </div>

            <button
              type="button"
              disabled={!ready || loading || !appConfig?.app_token}
              onClick={handleOneTimePayment}
              className="w-full rounded-lg bg-indigo-600 text-white py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
            >
              {loading ? 'Opening…' : 'Pay with UnivaPay'}
            </button>
          </div>
        ) : (
          <div className="mt-5 grid grid-cols-1 gap-3">
            <button
              disabled={!ready || loading || !appConfig?.app_token}
              onClick={() => handleSubscription('monthly')}
              className="w-full rounded-lg border border-gray-300 bg-white py-3 text-sm font-medium hover:bg-gray-50 disabled:opacity-60"
            >
              {loading ? 'Opening…' : 'Monthly — ¥10,000'}
            </button>
            <button
              disabled={!ready || loading || !appConfig?.app_token}
              onClick={() => handleSubscription('6months')}
              className="w-full rounded-lg bg-indigo-600 text-white py-3 text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
            >
              {loading ? 'Opening…' : '6 Months — ¥58,000'}
            </button>
          </div>
        )}

        <button
          onClick={() => router.push('/home')}
          className="mt-6 w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
        >
          ← Back
        </button>

        <div className="mt-3 text-xs text-gray-500">
          Script loaded: {ready ? 'yes' : 'no'} · Config: {appConfig ? 'loaded' : 'loading'}
        </div>
      </div>
    </main>
  );
}