'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:5000';

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = () => {
    localStorage.removeItem('token');
    router.push('/');
  };

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) { router.push('/'); return; }
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/me`, { headers: { Authorization: `Bearer ${token}` } });
        const data = await res.json();
        if (res.ok) setUser(data.user);
        else { localStorage.removeItem('token'); router.push('/'); }
      } catch {
        localStorage.removeItem('token'); router.push('/');
      } finally { setLoading(false); }
    })();
  }, [router]);

  if (loading) return <main className="p-6">Loading…</main>;

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-gray-50">
      <div className="bg-white shadow-lg rounded-2xl p-6 w-full max-w-md">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Welcome{user ? `, ${user.username}` : ''}</h1>
          <button
            onClick={logout}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-gray-50"
          >
            Logout
          </button>
        </div>
        <p className="text-sm text-gray-600 mt-1">Choose an action:</p>

        <div className="mt-6 grid grid-cols-1 gap-3">
          <button
            onClick={() => router.push('/buy')}
            className="w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
          >
            Buy Products
          </button>
          <button
            onClick={() => router.push('/subscribe')}
            className="w-full rounded-lg bg-indigo-600 text-white py-2 text-sm font-medium hover:bg-indigo-700"
          >
            Subscribe
          </button>
          <button
            onClick={() => router.push('/payments')}
            className="w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium hover:bg-gray-50"
          >
            View Payments
          </button>
        </div>
      </div>
    </main>
  );
}
