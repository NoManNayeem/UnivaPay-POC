'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

export default function PaymentsReturnPage() {
  const sp = useSearchParams();
  const router = useRouter();

  const chargeId = useMemo(() => sp.get('univapayChargeId') || '', [sp]);
  const tokenId = useMemo(() => sp.get('univapayTokenId') || '', [sp]);
  const status = useMemo(() => sp.get('status') || '', [sp]);

  const [seconds, setSeconds] = useState(4); // redirect countdown
  const [auto, setAuto] = useState(true);

  // auth guard
  useEffect(() => {
    const jwt = localStorage.getItem('token');
    if (!jwt) router.push('/');
  }, [router]);

  // auto-redirect to /payments after countdown
  useEffect(() => {
    if (!auto) return;
    if (seconds <= 0) {
      router.push('/payments');
      return;
    }
    const t = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [auto, seconds, router]);

  const banner = (() => {
    if (status.toLowerCase() === 'successful') {
      return {
        cls: 'border-green-200 bg-green-50 text-green-700',
        text: 'Payment authentication finished successfully. Final status will appear in your payments list.',
      };
    }
    if (status.toLowerCase() === 'failed' || status.toLowerCase() === 'error') {
      return {
        cls: 'border-red-200 bg-red-50 text-red-700',
        text: 'Payment authentication failed or was canceled. You can try again.',
      };
    }
    return {
      cls: 'border-amber-200 bg-amber-50 text-amber-800',
      text: 'You were redirected back from 3-D Secure. We will show the final result in your payments list shortly.',
    };
  })();

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-md">
        <h1 className="text-xl font-semibold">Returning from Bank</h1>
        <p className="text-sm text-gray-600 mt-1">
          We’ve received your 3-D Secure response. You can head to your payments list now.
        </p>

        <div className={`mt-4 rounded-md border p-3 text-sm ${banner.cls}`}>
          {banner.text}
        </div>

        <div className="mt-4 text-sm text-gray-700 space-y-1">
          <div>
            univapayChargeId: <code>{chargeId || '—'}</code>
          </div>
          <div>
            univapayTokenId: <code>{tokenId || '—'}</code>
          </div>
          <div>
            status: <code>{status || '—'}</code>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-between">
          <button
            onClick={() => router.push('/payments')}
            className="rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm font-medium hover:bg-indigo-700"
          >
            View Payments
          </button>

          <div className="text-xs text-gray-500">
            {auto ? (
              <button
                onClick={() => setAuto(false)}
                className="underline hover:no-underline"
              >
                Auto-redirect in {seconds}s — stop
              </button>
            ) : (
              <span>Auto-redirect paused</span>
            )}
          </div>
        </div>

        <button
          onClick={() => router.push('/home')}
          className="mt-4 w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
        >
          ← Back
        </button>
      </div>
    </main>
  );
}
