'use client';

import Script from 'next/script';
import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { postWithAuth } from '../../../lib/api';

const APP_ID = process.env.NEXT_PUBLIC_UNIVAPAY_APP_ID || '';
const RETURN_URL = process.env.NEXT_PUBLIC_UNIVAPAY_RETURN_URL || '';

export default function SubscribePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);     // UnivapayCheckout script loaded
  const [loading, setLoading] = useState(false); // submit state
  const [msg, setMsg] = useState({ type: '', text: '' });
  const mountedRef = useRef(true);

  // toggle this to redirect to payments after success
  const AUTO_REDIRECT = true;

  // auth guard
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) router.push('/');
  }, [router]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const setError = (t) => setMsg({ type: 'error', text: t });
  const setSuccess = (t) => setMsg({ type: 'success', text: t });

  const openTokenWidget = useCallback(async (plan) => {
    if (loading) return; // prevent double-taps
    if (!APP_ID) { setError('Missing NEXT_PUBLIC_UNIVAPAY_APP_ID'); return; }
    if (typeof window === 'undefined' || !window.UnivapayCheckout) {
      setError('UnivaPay widget is not ready yet.');
      return;
    }

    const periodMap = { monthly: 'monthly', '6months': 'semiannually' };
    const period = periodMap[plan];
    if (!period) { setError('Invalid plan'); return; }

    setMsg({ type: '', text: '' });
    setLoading(true);

    try {
      const checkout = window.UnivapayCheckout.create({
        appId: APP_ID,
        checkout: 'token',              // tokenization only
        tokenType: 'subscription',      // we need a subscription token
        subscriptionPeriod: period,     // "monthly" | "semiannually"
        redirect: RETURN_URL || undefined,

        onTokenCreated: async (tokenId) => {
          try {
            const data = await postWithAuth('/api/checkout/subscription', {
              transaction_token_id: tokenId,
              plan,
              redirect_endpoint: RETURN_URL || undefined,
            });

            const nextStatus = data?.univapay?.status || 'unknown';
            const subId = data?.univapay?.subscription_id || '—';
            if (!mountedRef.current) return;

            setSuccess(`Subscription created (id: ${subId}). Provider status: ${nextStatus}`);

            if (AUTO_REDIRECT) {
              // small delay to let user see the success toast
              setTimeout(() => {
                if (mountedRef.current) router.push('/payments?from=return');
              }, 900);
            }
          } catch (err) {
            if (!mountedRef.current) return;
            setError(err.message || 'Failed to create subscription on server');
          } finally {
            if (mountedRef.current) setLoading(false);
          }
        },

        onClose: () => {
          // user closed the popup; if we were still "loading", unlock
          if (mountedRef.current && loading) setLoading(false);
        },

        onError: (err) => {
          if (!mountedRef.current) return;
          setError(typeof err === 'string' ? err : (err?.message || 'Widget error'));
          setLoading(false);
        },
      });

      checkout.open();
    } catch (err) {
      setError(err?.message || 'Failed to open UnivaPay widget');
      setLoading(false);
    }
  }, [loading, router]);

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      {/* Load the UnivaPay widget JS */}
      <Script
        src="https://widget.univapay.com/client/checkout.js"
        strategy="afterInteractive"
        onLoad={() => setReady(true)}
      />

      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-md">
        <h1 className="text-xl font-semibold">Subscribe</h1>
        <p className="text-sm text-gray-600 mt-1">
          Choose a plan. A secure UnivaPay popup will collect your card and create a subscription token.
        </p>

        {!APP_ID && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Missing <code>NEXT_PUBLIC_UNIVAPAY_APP_ID</code> in <code>.env.local</code>.
          </div>
        )}

        {msg.text && (
          <div
            className={`mt-4 rounded-md border p-3 text-sm ${
              msg.type === 'error'
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-green-200 bg-green-50 text-green-700'
            }`}
          >
            {msg.text}
          </div>
        )}

        <div className="mt-5 grid grid-cols-1 gap-3">
          <button
            disabled={!ready || loading}
            onClick={() => openTokenWidget('monthly')}
            className="w-full rounded-lg border border-gray-300 bg-white py-3 text-sm font-medium hover:bg-gray-50 disabled:opacity-60"
          >
            {loading ? 'Opening…' : 'Monthly — ¥10,000'}
          </button>
          <button
            disabled={!ready || loading}
            onClick={() => openTokenWidget('6months')}
            className="w-full rounded-lg bg-indigo-600 text-white py-3 text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
          >
            {loading ? 'Opening…' : '6 Months — ¥58,000'}
          </button>
        </div>

        <button
          onClick={() => router.push('/home')}
          className="mt-6 w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
        >
          ← Back
        </button>

        <div className="mt-3 text-xs text-gray-500">
          Script loaded: {ready ? 'yes' : 'no'} · AppId: {APP_ID ? 'set' : 'missing'}
        </div>
      </div>
    </main>
  );
}
