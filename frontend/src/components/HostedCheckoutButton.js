'use client';

import Script from 'next/script';
import { useEffect, useRef, useState, useCallback } from 'react';

const APP_ID = process.env.NEXT_PUBLIC_UNIVAPAY_APP_ID || '';
const RETURN_URL = process.env.NEXT_PUBLIC_UNIVAPAY_RETURN_URL || '';

/**
 * HostedCheckoutButton
 * Props:
 *  - amount: integer JPY (required)
 *  - currency: 'jpy' | 'JPY' | string  (default: 'jpy')
 *  - label: string (default: 'Pay with UnivaPay')
 *  - paymentMethods: string[] (default: ['card'])
 *  - disabled: boolean (optional)
 *  - onOpened?: () => void
 *  - onClosed?: () => void
 *  - onError?: (err: Error | string) => void
 *
 * Notes:
 *  - Uses UnivaPay hosted checkout ("payment") — one-time payments.
 *  - Subscriptions should use token mode in the dedicated Subscribe page.
 */
export default function HostedCheckoutButton({
  amount,
  currency = 'jpy',
  label = 'Pay with UnivaPay',
  paymentMethods = ['card'],
  disabled = false,
  onOpened,
  onClosed,
  onError,
}) {
  const checkoutRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [opening, setOpening] = useState(false);

  // Detect readiness when script loads, and also if it was cached
  useEffect(() => {
    const checkReady = () => {
      if (typeof window !== 'undefined' && window.UnivapayCheckout && APP_ID) {
        setReady(true);
        return true;
      }
      return false;
    };
    if (!checkReady()) {
      const t = setInterval(() => {
        if (checkReady()) clearInterval(t);
      }, 150);
      return () => clearInterval(t);
    }
  }, []);

  // Cleanup any still-referenced checkout on unmount
  useEffect(() => {
    return () => {
      try {
        // Some widget versions expose close(); if not, ignore.
        if (checkoutRef.current && typeof checkoutRef.current.close === 'function') {
          checkoutRef.current.close();
        }
      } catch {}
      checkoutRef.current = null;
    };
  }, []);

  const openCheckout = useCallback(() => {
    const fail = (err) => {
      if (onError) onError(err);
      else console.error(err);
    };

    if (opening) return;
    if (!APP_ID) return fail('Missing NEXT_PUBLIC_UNIVAPAY_APP_ID');
    if (typeof window === 'undefined' || !window.UnivapayCheckout) return fail('UnivaPay widget is not ready');
    const amt = Number(amount);
    if (!Number.isInteger(amt) || amt <= 0) return fail('Amount must be a positive integer (JPY)');

    setOpening(true);
    try {
      const checkout = window.UnivapayCheckout.create({
        appId: APP_ID,
        checkout: 'payment', // hosted payment flow (one-time)
        amount: amt,
        currency: String(currency).toLowerCase(), // 'jpy'
        cvvAuthorize: true,
        paymentMethods, // e.g. ['card', 'bank_transfer', ...]
        redirect: RETURN_URL || undefined,

        onClose: () => {
          setOpening(false);
          if (onClosed) onClosed();
        },

        onError: (err) => {
          setOpening(false);
          fail(typeof err === 'string' ? err : (err?.message || 'Widget error'));
        },
      });

      checkoutRef.current = checkout;
      if (onOpened) onOpened();
      checkout.open();
    } catch (err) {
      setOpening(false);
      fail(err?.message || err || 'Failed to open UnivaPay widget');
    }
  }, [amount, currency, paymentMethods, onClosed, onError, onOpened, opening]);

  return (
    <>
      {/* Load the widget script once */}
      <Script
        src="https://widget.univapay.com/client/checkout.js"
        strategy="afterInteractive"
        onLoad={() => setReady(true)}
      />

      <button
        type="button"
        onClick={openCheckout}
        disabled={!ready || opening || disabled || !Number.isInteger(Number(amount)) || Number(amount) <= 0}
        className="w-full rounded-lg bg-indigo-600 text-white py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
        aria-busy={opening ? 'true' : 'false'}
      >
        {opening ? 'Opening…' : label}
      </button>

      {!APP_ID && (
        <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2">
          Missing <code>NEXT_PUBLIC_UNIVAPAY_APP_ID</code> in <code>.env.local</code>.
        </div>
      )}
    </>
  );
}
