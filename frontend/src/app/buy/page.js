'use client';

import Script from 'next/script';
import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { postWithAuth } from '../../../lib/api';

const APP_ID = process.env.NEXT_PUBLIC_UNIVAPAY_APP_ID || '';
const RETURN_URL = process.env.NEXT_PUBLIC_UNIVAPAY_RETURN_URL || '';

export default function BuyPage() {
  const router = useRouter();
  const [itemName, setItemName] = useState('');
  const [amount, setAmount] = useState('');
  const [ready, setReady] = useState(false);     // UnivapayCheckout script loaded
  const [loading, setLoading] = useState(false); // submit state
  const [msg, setMsg] = useState({ type: '', text: '' });

  // simple auth guard
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) router.push('/');
  }, [router]);

  const setError = (t) => setMsg({ type: 'error', text: t });
  const setSuccess = (t) => setMsg({ type: 'success', text: t });

  const pay = useCallback(async () => {
    setMsg({ type: '', text: '' });

    const amt = Number(amount);
    if (!itemName.trim()) return setError('Item name is required.');
    if (!Number.isInteger(amt) || amt <= 0) return setError('Amount must be a positive integer (JPY).');

    if (!APP_ID) return setError('Missing NEXT_PUBLIC_UNIVAPAY_APP_ID');
    if (typeof window === 'undefined' || !window.UnivapayCheckout) {
      return setError('UnivaPay widget is not ready yet.');
    }

    setLoading(true);
    try {
      // 1) Create token via widget (one-time)
      const checkout = window.UnivapayCheckout.create({
        appId: APP_ID,
        checkout: 'token',         // tokenization flow
        tokenType: 'one_time',     // create a one-time token
        cvvAuthorize: true,
        // If your store enforces 3DS at token/charge time, allow redirect back:
        redirect: RETURN_URL || undefined,
        paymentMethods: ['card'],

        onTokenCreated: async (tokenId) => {
          try {
            // 2) Use token server-side to create a charge
            const data = await postWithAuth('/api/checkout/charge', {
              transaction_token_id: tokenId,
              item_name: itemName.trim(),
              amount: amt,
              redirect_endpoint: RETURN_URL || undefined,
            });

            // 3) If UnivaPay instructs a redirect (e.g., 3DS), follow it
            const redirectInfo = data?.univapay?.redirect;
            if (redirectInfo?.endpoint) {
              window.location.href = redirectInfo.endpoint;
              return;
            }

            setSuccess(`Charge submitted. Provider status: ${data?.univapay?.status || 'unknown'}`);
            setItemName('');
            setAmount('');
          } catch (err) {
            setError(err.message || 'Failed to create charge on server');
          } finally {
            setLoading(false);
          }
        },

        onClose: () => {
          if (loading) setLoading(false);
        },

        onError: (err) => {
          setError(typeof err === 'string' ? err : (err?.message || 'Widget error'));
          setLoading(false);
        },
      });

      checkout.open();
    } catch (err) {
      setError(err?.message || 'Failed to open UnivaPay widget');
      setLoading(false);
    }
  }, [amount, itemName, loading]);

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      {/* Load UnivaPay widget script */}
      <Script
        src="https://widget.univapay.com/client/checkout.js"
        strategy="afterInteractive"
        onLoad={() => setReady(true)}
      />

      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-md">
        <h1 className="text-xl font-semibold">Buy Products</h1>
        <p className="text-sm text-gray-600 mt-1">
          Enter an item and amount, then pay via UnivaPay.
        </p>

        {!APP_ID && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Missing <code>NEXT_PUBLIC_UNIVAPAY_APP_ID</code> in <code>.env.local</code>.
          </div>
        )}

        {msg.text && (
          <div className={`mt-4 rounded-md border p-3 text-sm ${
            msg.type === 'error'
              ? 'border-red-200 bg-red-50 text-red-700'
              : 'border-green-200 bg-green-50 text-green-700'
          }`}>
            {msg.text}
          </div>
        )}

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
            disabled={!ready || loading}
            onClick={pay}
            className="w-full rounded-lg bg-indigo-600 text-white py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
          >
            {loading ? 'Opening…' : 'Pay with UnivaPay'}
          </button>

          <button
            type="button"
            onClick={() => router.push('/home')}
            className="w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
          >
            ← Back
          </button>
        </div>

        <div className="mt-3 text-xs text-gray-500">
          Script loaded: {ready ? 'yes' : 'no'} · AppId: {APP_ID ? 'set' : 'missing'}
        </div>
      </div>
    </main>
  );
}
