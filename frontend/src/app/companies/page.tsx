"use client";

import { useEffect, useState } from "react";

import { API_BASE as API } from "@/lib/api";

type Company = {
  name: string;
  tier: string;
  h1b_status: string;
  priority: number;
  careers_url: string;
  notes: string;
};

const tierLabel: Record<string, string> = {
  model_provider: "Model Provider",
  big_tech_cloud_ai: "Big Tech / Cloud AI",
  gtm_revenue_intelligence: "GTM & Revenue Intel",
  data_startup_intelligence: "Data & Startup Intel",
  ai_native_gtm: "AI-Native GTM",
};

const tierColor: Record<string, string> = {
  model_provider: "bg-purple-100 text-purple-800",
  big_tech_cloud_ai: "bg-blue-100 text-blue-800",
  gtm_revenue_intelligence: "bg-orange-100 text-orange-800",
  data_startup_intelligence: "bg-teal-100 text-teal-800",
  ai_native_gtm: "bg-pink-100 text-pink-800",
};

const h1bColor: Record<string, string> = {
  confirmed: "text-green-700",
  likely: "text-yellow-700",
  unknown: "text-gray-400",
};

export default function Companies() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/companies`)
      .then((res) => res.json())
      .then((data) => {
        setCompanies(data.companies);
        setLoading(false);
      });
  }, []);

  if (loading) return <main className="p-8 text-gray-500">Loading...</main>;

  return (
    <main className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Target Companies</h1>
        <span className="text-sm text-gray-500">
          {companies.length} companies
        </span>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 w-10">
                #
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">
                Company
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">
                Tier
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">
                H1B
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">
                Notes
              </th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">
                Careers
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {companies.map((company) => (
              <tr key={company.name} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-400">{company.priority}</td>
                <td className="px-4 py-3 font-medium">{company.name}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${tierColor[company.tier] || "bg-gray-100"}`}
                  >
                    {tierLabel[company.tier] || company.tier}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`text-xs font-medium ${h1bColor[company.h1b_status] || "text-gray-400"}`}
                  >
                    {company.h1b_status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {company.notes || "--"}
                </td>
                <td className="px-4 py-3 text-right">
                  <a
                    href={company.careers_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Careers
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
