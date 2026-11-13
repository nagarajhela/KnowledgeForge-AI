"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface PlanItem {
  tier: string;
  name: string;
  monthly_price_usd: number;
  monthly_document_limit: number;
  storage_limit_mb: number;
  monthly_ai_request_limit: number;
  team_member_limit: number;
  knowledge_base_limit: number;
}

interface BillingOverview {
  subscription: { plan_tier: string; status: string };
  usage: Record<string, number>;
  available_plans: PlanItem[];
}

export default function BillingPage() {
  const [data, setData] = useState<BillingOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("kf_access_token");
    const orgId = localStorage.getItem("kf_org_id");
    if (!token || !orgId) return;
    apiFetch<BillingOverview>("/billing", { token, organizationId: orgId })
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }, []);

  async function selectPlan(tier: string) {
    const token = localStorage.getItem("kf_access_token");
    const orgId = localStorage.getItem("kf_org_id");
    if (!token || !orgId) return;
    await apiFetch("/billing/plan", {
      method: "POST",
      token,
      organizationId: orgId,
      body: JSON.stringify({ plan_tier: tier }),
    });
    const updated = await apiFetch<BillingOverview>("/billing", { token, organizationId: orgId });
    setData(updated);
  }

  return (
    <main className="max-w-5xl mx-auto py-10 px-6">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Subscription & Quotas</h1>
          <p className="text-sm text-slate-500 mt-1">Manage monthly document, token, and team seat limits.</p>
        </div>
        <Link href="/" className="text-sm font-medium text-slate-700 hover:text-slate-900">
          Back to Workspace
        </Link>
      </div>

      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

      {data && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {data.available_plans.map((plan) => {
            const active = data.subscription.plan_tier === plan.tier;
            return (
              <div key={plan.tier} className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col justify-between">
                <div>
                  <h2 className="text-base font-semibold text-slate-900">{plan.name}</h2>
                  <p className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-2">
                    ${plan.monthly_price_usd}
                    <span className="text-xs font-sans text-slate-500">/mo</span>
                  </p>
                  <ul className="mt-4 space-y-2 text-xs text-slate-600 font-mono tabular-nums">
                    <li>{plan.monthly_document_limit.toLocaleString()} documents</li>
                    <li>{plan.storage_limit_mb.toLocaleString()} MB storage</li>
                    <li>{plan.monthly_ai_request_limit.toLocaleString()} AI queries/mo</li>
                    <li>{plan.team_member_limit.toLocaleString()} members</li>
                    <li>{plan.knowledge_base_limit.toLocaleString()} knowledge bases</li>
                  </ul>
                </div>
                <button
                  onClick={() => selectPlan(plan.tier)}
                  disabled={active}
                  className={`mt-6 w-full py-2 px-3 rounded-lg text-xs font-medium ${
                    active
                      ? "bg-slate-100 text-slate-500 cursor-default"
                      : "bg-slate-900 text-white hover:bg-slate-800"
                  }`}
                >
                  {active ? "Current Plan" : `Switch to ${plan.name}`}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
