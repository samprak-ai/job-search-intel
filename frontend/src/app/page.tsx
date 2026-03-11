import Link from "next/link";

export default function Home() {
  return (
    <main className="p-8">
      <h1 className="text-3xl font-bold mb-2">Job Search Intel</h1>
      <p className="text-gray-500 mb-8">
        Track target companies, discover roles, score matches, and prep for
        interviews.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Link
          href="/dashboard"
          className="block p-6 bg-white rounded-lg border border-gray-200 hover:border-blue-400 transition-colors"
        >
          <h2 className="text-lg font-semibold mb-2">Dashboard</h2>
          <p className="text-sm text-gray-500">
            View discovered roles with match scores, filter by company and tier.
          </p>
        </Link>
        <Link
          href="/companies"
          className="block p-6 bg-white rounded-lg border border-gray-200 hover:border-blue-400 transition-colors"
        >
          <h2 className="text-lg font-semibold mb-2">Companies</h2>
          <p className="text-sm text-gray-500">
            Browse 25 target companies by tier, H1B status, and priority.
          </p>
        </Link>
      </div>
    </main>
  );
}
