'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:5000';

function formatJPY(n) {
  try {
    return new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(n);
  } catch {
    return `¥${n ?? '-'}`;
  }
}

function formatDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleString();
}

function CopyButton({ value, label = 'Copy' }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value || '');
          setCopied(true);
          setTimeout(() => setCopied(false), 900);
        } catch {}
      }}
      className="ml-2 inline-flex items-center rounded-md border border-gray-300 bg-white px-2 py-0.5 text-[11px] font-medium hover:bg-gray-50"
      disabled={!value}
      title={value ? `Copy ${value}` : 'Nothing to copy'}
    >
      {copied ? 'Copied' : label}
    </button>
  );
}

function RowDetails({ row }) {
  const p = row?.provider;
  const hasProvider = !!p;

  return (
    <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
      <div className="font-semibold text-gray-800">Local Record</div>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
        <div>Payment ID</div><div>#{row.id}</div>
        <div>User</div><div>{row.user || '—'}</div>
        <div>Kind</div><div className="capitalize">{row.kind}</div>
        <div>Item Name</div><div>{row.item_name || '—'}</div>
        <div>Plan</div><div>{row.plan ? (row.plan === '6months' ? '6 Months' : row.plan) : '—'}</div>
        <div>Amount</div><div>{formatJPY(row.amount_jpy)}</div>
        <div>Created</div><div>{formatDate(row.created_at)}</div>
      </div>

      <div className="mt-4 font-semibold text-gray-800">Provider (UnivaPay)</div>
      {!hasProvider ? (
        <div className="mt-2 text-gray-500">No provider mapping found for this payment yet.</div>
      ) : (
        <>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            <div>Provider</div><div>{p.provider || 'univapay'}</div>
            <div>Status</div><div>{p.status || '—'}</div>
            <div>Currency</div><div>{p.currency || 'JPY'}</div>
            <div>Provider Created</div><div>{formatDate(p.created_at)}</div>
            <div>Provider Updated</div><div>{formatDate(p.updated_at)}</div>
            <div>Charge ID</div>
            <div className="truncate">
              <code className="break-all">{p.charge_id || '—'}</code>
              {!!p.charge_id && <CopyButton value={p.charge_id} />}
            </div>
            <div>Subscription ID</div>
            <div className="truncate">
              <code className="break-all">{p.subscription_id || '—'}</code>
              {!!p.subscription_id && <CopyButton value={p.subscription_id} />}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function PaymentsPage() {
  const router = useRouter();
  const sp = useSearchParams();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [openIds, setOpenIds] = useState({}); // expand/collapse details per row

  // When coming from /payments/return, auto-refresh briefly to catch webhook updates
  const fromReturn = useMemo(() => sp.get('from') === 'return', [sp]);
  const autorefreshSecs = 30; // total seconds to auto-refresh
  const [secondsLeft, setSecondsLeft] = useState(fromReturn ? autorefreshSecs : 0);
  const intervalRef = useRef(null);

  // auth guard
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) router.push('/');
  }, [router]);

  const fetchRows = async () => {
    const token = localStorage.getItem('token');
    if (!token) { router.push('/'); return; }
    setErr('');
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/payments`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Failed to load payments');
      // Expecting each payment to include `provider` object if you applied the BE update
      setRows(Array.isArray(data.payments) ? data.payments : []);
    } catch (e) {
      setErr(e.message || 'Error loading payments');
    } finally {
      setLoading(false);
    }
  };

  // initial load
  useEffect(() => {
    fetchRows();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // short auto-refresh loop after returning from 3DS
  useEffect(() => {
    if (!fromReturn || secondsLeft <= 0 || intervalRef.current) return;

    intervalRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        const next = s - 5;
        if (next <= 0) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
          return 0;
        }
        return next;
      });
      fetchRows();
    }, 5000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromReturn, secondsLeft]);

  const toggleOpen = (id) => {
    setOpenIds((m) => ({ ...m, [id]: !m[id] }));
  };

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-4xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-semibold">Your Payments</h1>
          <div className="flex items-center gap-2">
            {fromReturn && secondsLeft > 0 && (
              <span className="text-xs text-gray-500">
                Auto-refreshing… {secondsLeft}s
              </span>
            )}
            <button
              onClick={fetchRows}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-gray-50"
            >
              Refresh
            </button>
            <button
              onClick={() => router.push('/home')}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-gray-50"
            >
              ← Back
            </button>
          </div>
        </div>

        {loading && <p className="mt-4 text-sm text-gray-600">Loading…</p>}
        {err && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {err}
          </div>
        )}

        {!loading && !err && (
          <>
            {rows.length === 0 ? (
              <div className="mt-6 rounded-lg border border-gray-200 p-6 text-center">
                <p className="text-sm text-gray-600">No payments yet.</p>
                <div className="mt-4 flex items-center justify-center gap-3">
                  <button
                    onClick={() => router.push('/buy')}
                    className="rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm font-medium hover:bg-indigo-700"
                  >
                    Buy a Product
                  </button>
                  <button
                    onClick={() => router.push('/subscribe')}
                    className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50"
                  >
                    Subscribe
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-600 border-b">
                      <th className="py-2 pr-4">#</th>
                      <th className="py-2 pr-4">Kind</th>
                      <th className="py-2 pr-4">Item / Plan</th>
                      <th className="py-2 pr-4">Amount</th>
                      <th className="py-2 pr-4">Created</th>
                      <th className="py-2 pr-4">Provider Status</th>
                      <th className="py-2 pr-4">Provider IDs</th>
                      <th className="py-2 pr-4">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const p = r.provider || null;
                      const pid = `row-${r.id}`;
                      const itemOrPlan = r.kind === 'product'
                        ? (r.item_name || '—')
                        : (r.plan === '6months' ? '6 Months' : (r.plan || '—'));

                      return (
                        <tr key={r.id} className="border-b last:border-0 align-top">
                          <td className="py-2 pr-4">{r.id}</td>
                          <td className="py-2 pr-4 capitalize">{r.kind}</td>
                          <td className="py-2 pr-4">{itemOrPlan}</td>
                          <td className="py-2 pr-4">{formatJPY(r.amount_jpy)}</td>
                          <td className="py-2 pr-4">{formatDate(r.created_at)}</td>
                          <td className="py-2 pr-4">
                            {p?.status ?? '—'}
                          </td>
                          <td className="py-2 pr-4">
                            <div className="max-w-[260px] truncate">
                              <div className="truncate">
                                <span className="text-gray-500">ch:</span>{' '}
                                <code className="break-all">{p?.charge_id || '—'}</code>
                                {!!p?.charge_id && <CopyButton value={p.charge_id} />}
                              </div>
                              <div className="truncate">
                                <span className="text-gray-500">sub:</span>{' '}
                                <code className="break-all">{p?.subscription_id || '—'}</code>
                                {!!p?.subscription_id && <CopyButton value={p.subscription_id} />}
                              </div>
                            </div>
                          </td>
                          <td className="py-2 pr-4">
                            <button
                              onClick={() => toggleOpen(pid)}
                              className="rounded-md border border-gray-300 bg-white px-3 py-1 text-xs font-medium hover:bg-gray-50"
                            >
                              {openIds[pid] ? 'Hide' : 'View'}
                            </button>
                            {openIds[pid] && <RowDetails row={r} />}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
