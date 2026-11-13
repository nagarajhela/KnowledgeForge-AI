import React, { useMemo, useState } from "react";
import {
  BookOpen,
  Building2,
  Check,
  Copy,
  CreditCard,
  FileText,
  Key,
  MessageSquare,
  Plus,
  Send,
  Shield,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
  Users,
  BarChart3,
} from "lucide-react";

type NavSection = "chat" | "knowledge-bases" | "team" | "analytics" | "billing" | "api-docs";
type Role = "owner" | "admin" | "editor" | "viewer" | "billing_manager";

interface Organization {
  id: string;
  name: string;
  slug: string;
  role: Role;
  planTier: "free" | "starter" | "pro" | "enterprise";
}

interface KnowledgeBase {
  id: string;
  organizationId: string;
  name: string;
  description: string;
  llmProvider: string;
  llmModel: string;
  chunkSize: number;
  chunkOverlap: number;
  accessScope: "organization_wide" | "selected_teams" | "selected_users";
}

interface DocumentItem {
  id: string;
  organizationId: string;
  knowledgeBaseId: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  checksum: string;
  status: "completed" | "queued" | "processing" | "failed";
  chunks: { id: string; pageNumber: number; content: string }[];
  createdAt: string;
}

interface Citation {
  documentId: string;
  documentName: string;
  chunkId: string;
  pageNumber: number;
  excerpt: string;
  relevanceScore: number;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  confidenceScore?: number;
  feedback?: "up" | "down";
}

interface TeamMember {
  id: string;
  organizationId: string;
  name: string;
  email: string;
  role: Role;
}

interface APIKeyRecord {
  id: string;
  organizationId: string;
  name: string;
  prefix: string;
  scopes: string[];
  requestCount: number;
  active: boolean;
}

const INITIAL_ORGS: Organization[] = [
  { id: "org-acme-01", name: "Acme Enterprise", slug: "acme-enterprise", role: "owner", planTier: "pro" },
  { id: "org-nova-02", name: "Nova BioLabs", slug: "nova-biolabs", role: "editor", planTier: "starter" },
];

const INITIAL_KBS: KnowledgeBase[] = [
  {
    id: "kb-hr-01",
    organizationId: "org-acme-01",
    name: "Employee Handbook & HR Policy",
    description: "Leave entitlements, expense reimbursements, and onboarding standards.",
    llmProvider: "openai",
    llmModel: "gpt-4o-mini",
    chunkSize: 512,
    chunkOverlap: 64,
    accessScope: "organization_wide",
  },
  {
    id: "kb-sec-02",
    organizationId: "org-acme-01",
    name: "Security & SOC 2 Controls",
    description: "Tenant isolation policies, encryption standards, and incident runbooks.",
    llmProvider: "anthropic",
    llmModel: "claude-3-5-sonnet",
    chunkSize: 640,
    chunkOverlap: 80,
    accessScope: "selected_teams",
  },
  {
    id: "kb-nova-01",
    organizationId: "org-nova-02",
    name: "Clinical Lab SOPs",
    description: "Isolated Nova BioLabs standard operating procedures.",
    llmProvider: "ollama",
    llmModel: "llama3.1:8b",
    chunkSize: 512,
    chunkOverlap: 64,
    accessScope: "organization_wide",
  },
];

const INITIAL_DOCS: DocumentItem[] = [
  {
    id: "doc-handbook-2026",
    organizationId: "org-acme-01",
    knowledgeBaseId: "kb-hr-01",
    filename: "Employee_Handbook_2026.pdf",
    mimeType: "application/pdf",
    sizeBytes: 428190,
    checksum: "8f4b2c9d1a0e3f7c",
    status: "completed",
    createdAt: "2026-11-10",
    chunks: [
      {
        id: "chk-101",
        pageNumber: 14,
        content:
          "Full-time employees receive 20 paid vacation days per calendar year. Unused annual leave up to 5 days may carry over into Q1 of the following year with manager approval.",
      },
      {
        id: "chk-102",
        pageNumber: 22,
        content:
          "Remote work equipment stipends are reimbursed up to $1,200 per employee every 24 months upon submitting receipts in the finance portal.",
      },
    ],
  },
  {
    id: "doc-soc2-controls",
    organizationId: "org-acme-01",
    knowledgeBaseId: "kb-sec-02",
    filename: "Tenant_Isolation_Architecture.md",
    mimeType: "text/markdown",
    sizeBytes: 68420,
    checksum: "3c1e9a44b2d8071f",
    status: "completed",
    createdAt: "2026-11-11",
    chunks: [
      {
        id: "chk-201",
        pageNumber: 3,
        content:
          "All tenant-scoped queries must filter by organization_id resolved server-side via get_current_tenant(). Client-supplied organization_id values in request payloads are ignored. Optional PostgreSQL RLS policies enforce session-local tenant checks.",
      },
    ],
  },
  {
    id: "doc-nova-sop",
    organizationId: "org-nova-02",
    knowledgeBaseId: "kb-nova-01",
    filename: "BioSafety_Protocol_v4.pdf",
    mimeType: "application/pdf",
    sizeBytes: 312000,
    checksum: "a91c0022e84b11c3",
    status: "completed",
    createdAt: "2026-11-12",
    chunks: [
      {
        id: "chk-301",
        pageNumber: 7,
        content:
          "Cryogenic storage units in Bay B must maintain -80C +/- 2C with dual-redundant telemetry alerts routed to the Lab Director.",
      },
    ],
  },
];

const INITIAL_MEMBERS: TeamMember[] = [
  { id: "usr-1", organizationId: "org-acme-01", name: "Elena Vance", email: "elena@acme.io", role: "owner" },
  { id: "usr-2", organizationId: "org-acme-01", name: "Marcus Chen", email: "marcus@acme.io", role: "admin" },
  { id: "usr-3", organizationId: "org-acme-01", name: "Priya Nair", email: "priya@acme.io", role: "viewer" },
  { id: "usr-4", organizationId: "org-nova-02", name: "Dr. Aris Thorne", email: "aris@novabiolabs.com", role: "owner" },
];

const INITIAL_KEYS: APIKeyRecord[] = [
  {
    id: "key-1",
    organizationId: "org-acme-01",
    name: "Internal Slack Bot",
    prefix: "kf_live_9fA2cX7q",
    scopes: ["kb:read", "chat:ask"],
    requestCount: 1428,
    active: true,
  },
];

const PLAN_DETAILS = [
  { tier: "free", name: "Free", price: 0, docs: 25, storageMb: 100, requests: 250, seats: 5, kbs: 3 },
  { tier: "starter", name: "Starter", price: 49, docs: 250, storageMb: 2048, requests: 5000, seats: 20, kbs: 15 },
  { tier: "pro", name: "Pro", price: 199, docs: 2500, storageMb: 25600, requests: 50000, seats: 100, kbs: 100 },
  { tier: "enterprise", name: "Enterprise", price: 799, docs: 100000, storageMb: 512000, requests: 1000000, seats: 5000, kbs: 2000 },
] as const;

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

export default function App() {
  const [nav, setNav] = useState<NavSection>("chat");
  const [orgs, setOrgs] = useState<Organization[]>(INITIAL_ORGS);
  const [activeOrgId, setActiveOrgId] = useState<string>(INITIAL_ORGS[0].id);
  const [kbs, setKbs] = useState<KnowledgeBase[]>(INITIAL_KBS);
  const [docs, setDocs] = useState<DocumentItem[]>(INITIAL_DOCS);
  const [members, setMembers] = useState<TeamMember[]>(INITIAL_MEMBERS);
  const [apiKeys, setApiKeys] = useState<APIKeyRecord[]>(INITIAL_KEYS);

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>(["kb-hr-01", "kb-sec-02"]);
  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState<Record<string, ChatMessage[]>>({
    "org-acme-01": [
      {
        id: "msg-welcome",
        role: "assistant",
        content:
          "Ask any question across your organization's permitted knowledge bases. Every answer is grounded strictly in retrieved document chunks with verifiable citations.",
        confidenceScore: 0.94,
        citations: [
          {
            documentId: "doc-handbook-2026",
            documentName: "Employee_Handbook_2026.pdf",
            chunkId: "chk-101",
            pageNumber: 14,
            excerpt:
              "Full-time employees receive 20 paid vacation days per calendar year. Unused annual leave up to 5 days may carry over into Q1...",
            relevanceScore: 0.92,
          },
        ],
      },
    ],
    "org-nova-02": [],
  });
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  // Forms & interactive feedback state
  const [newKbName, setNewKbName] = useState("");
  const [newKbModel, setNewKbModel] = useState("gpt-4o-mini");
  const [targetKbForUpload, setTargetKbForUpload] = useState("kb-hr-01");
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("viewer");

  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);

  const [backendUrl, setBackendUrl] = useState("http://localhost:8000/api/v1");

  const activeOrg = useMemo(
    () => orgs.find((o) => o.id === activeOrgId) ?? orgs[0],
    [orgs, activeOrgId]
  );

  // Strict tenant isolation filtering matching backend TenantRepository
  const orgKbs = useMemo(
    () => kbs.filter((kb) => kb.organizationId === activeOrg.id),
    [kbs, activeOrg.id]
  );
  const orgDocs = useMemo(
    () => docs.filter((d) => d.organizationId === activeOrg.id),
    [docs, activeOrg.id]
  );
  const orgMembers = useMemo(
    () => members.filter((m) => m.organizationId === activeOrg.id),
    [members, activeOrg.id]
  );
  const orgKeys = useMemo(
    () => apiKeys.filter((k) => k.organizationId === activeOrg.id),
    [apiKeys, activeOrg.id]
  );
  const orgMessages = chatHistory[activeOrg.id] ?? [];

  function switchOrg(orgId: string) {
    setActiveOrgId(orgId);
    const nextKbs = kbs.filter((kb) => kb.organizationId === orgId);
    setSelectedKbIds(nextKbs.map((k) => k.id));
    setTargetKbForUpload(nextKbs[0]?.id ?? "");
    setActiveCitation(null);
    setUploadNotice(null);
  }

  function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: q,
    };

    // Hybrid term + overlap retrieval strictly within activeOrg.id & selectedKbIds
    const qTerms = q
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((t) => t.length >= 3);

    const candidateChunks: { doc: DocumentItem; chunk: DocumentItem["chunks"][number]; score: number }[] = [];
    for (const doc of orgDocs) {
      if (!selectedKbIds.includes(doc.knowledgeBaseId)) continue;
      for (const chunk of doc.chunks) {
        const lower = chunk.content.toLowerCase();
        const matches = qTerms.filter((t) => lower.includes(t)).length;
        const score = qTerms.length > 0 ? Math.min(0.98, 0.35 + (matches / qTerms.length) * 0.62) : 0;
        if (matches > 0) {
          candidateChunks.push({ doc, chunk, score });
        }
      }
    }
    candidateChunks.sort((a, b) => b.score - a.score);
    const topHits = candidateChunks.slice(0, 3);

    let assistantMsg: ChatMessage;
    if (topHits.length === 0) {
      assistantMsg = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content:
          "I could not find sufficient verified evidence in the selected knowledge bases for this organization to answer that question. Try uploading relevant documentation or broadening your selected knowledge bases.",
        confidenceScore: 0.14,
        citations: [],
      };
    } else {
      const citations: Citation[] = topHits.map((h) => ({
        documentId: h.doc.id,
        documentName: h.doc.filename,
        chunkId: h.chunk.id,
        pageNumber: h.chunk.pageNumber,
        excerpt: h.chunk.content,
        relevanceScore: Number(h.score.toFixed(2)),
      }));
      assistantMsg = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: `${topHits[0].chunk.content} [Source 1]${
          topHits[1] ? ` Additionally, ${topHits[1].chunk.content} [Source 2]` : ""
        }`,
        citations,
        confidenceScore: Number((topHits.reduce((s, h) => s + h.score, 0) / topHits.length).toFixed(2)),
      };
      setActiveCitation(citations[0]);
    }

    setChatHistory((prev) => ({
      ...prev,
      [activeOrg.id]: [...(prev[activeOrg.id] ?? []), userMsg, assistantMsg],
    }));
    setQuestion("");
  }

  function handleCreateKb(e: React.FormEvent) {
    e.preventDefault();
    if (!newKbName.trim()) return;
    const kb: KnowledgeBase = {
      id: `kb-${Date.now()}`,
      organizationId: activeOrg.id,
      name: newKbName.trim(),
      description: "Configured with hybrid pgvector + FTS retrieval and token-aware chunking.",
      llmProvider: newKbModel.startsWith("claude") ? "anthropic" : "openai",
      llmModel: newKbModel,
      chunkSize: 512,
      chunkOverlap: 64,
      accessScope: "organization_wide",
    };
    setKbs((prev) => [kb, ...prev]);
    setSelectedKbIds((prev) => [...prev, kb.id]);
    setTargetKbForUpload(kb.id);
    setNewKbName("");
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !targetKbForUpload) return;
    const text = await file.text();
    const checksum = await sha256Hex(text);

    const duplicate = orgDocs.find(
      (d) => d.knowledgeBaseId === targetKbForUpload && d.checksum === checksum
    );
    if (duplicate) {
      setUploadNotice(`Deduplicated: "${file.name}" matches existing checksum ${checksum} (${duplicate.filename}).`);
      return;
    }

    const words = text.split(/\s+/).filter(Boolean);
    const chunkSize = 80;
    const chunks: DocumentItem["chunks"] = [];
    for (let i = 0; i < Math.max(1, words.length); i += chunkSize) {
      const slice = words.slice(i, i + chunkSize).join(" ");
      if (slice.trim()) {
        chunks.push({
          id: `chk-${Date.now()}-${i}`,
          pageNumber: Math.floor(i / chunkSize) + 1,
          content: slice,
        });
      }
    }

    const newDoc: DocumentItem = {
      id: `doc-${Date.now()}`,
      organizationId: activeOrg.id,
      knowledgeBaseId: targetKbForUpload,
      filename: file.name,
      mimeType: file.type || "text/plain",
      sizeBytes: file.size,
      checksum,
      status: "completed",
      chunks,
      createdAt: new Date().toISOString().slice(0, 10),
    };
    setDocs((prev) => [newDoc, ...prev]);
    setUploadNotice(`Ingested "${file.name}" (${chunks.length} chunks, SHA-256 ${checksum}).`);
    e.target.value = "";
  }

  function handleInviteMember(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setMembers((prev) => [
      ...prev,
      {
        id: `usr-${Date.now()}`,
        organizationId: activeOrg.id,
        name: inviteEmail.split("@")[0],
        email: inviteEmail.trim().toLowerCase(),
        role: inviteRole,
      },
    ]);
    setInviteEmail("");
  }

  function handleCreateApiKey(e: React.FormEvent) {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    const randomPart = Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    const fullKey = `kf_live_${randomPart.slice(0, 28)}`;
    const record: APIKeyRecord = {
      id: `key-${Date.now()}`,
      organizationId: activeOrg.id,
      name: newKeyName.trim(),
      prefix: fullKey.slice(0, 16),
      scopes: ["kb:read", "chat:ask"],
      requestCount: 0,
      active: true,
    };
    setApiKeys((prev) => [record, ...prev]);
    setRevealedKey(fullKey);
    setNewKeyName("");
  }

  function setPlan(tier: Organization["planTier"]) {
    setOrgs((prev) => prev.map((o) => (o.id === activeOrg.id ? { ...o, planTier: tier } : o)));
  }

  const navItems: { id: NavSection; label: string; icon: React.ReactNode }[] = [
    { id: "chat", label: "RAG Chat", icon: <MessageSquare className="w-4 h-4" /> },
    { id: "knowledge-bases", label: "Knowledge Bases", icon: <BookOpen className="w-4 h-4" /> },
    { id: "team", label: "Team & RBAC", icon: <Users className="w-4 h-4" /> },
    { id: "analytics", label: "Analytics & Keys", icon: <BarChart3 className="w-4 h-4" /> },
    { id: "billing", label: "Billing & Quotas", icon: <CreditCard className="w-4 h-4" /> },
    { id: "api-docs", label: "API & Architecture", icon: <Shield className="w-4 h-4" /> },
  ];

  const sectionTitles: Record<NavSection, string> = {
    chat: "Grounded RAG Assistant",
    "knowledge-bases": "Knowledge Bases & Ingestion",
    team: "Members & Role-Based Access",
    analytics: "Usage Analytics & API Keys",
    billing: "Plan Quotas & Billing",
    "api-docs": "FastAPI Endpoints & Isolation",
  };

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900">
      {/* Sidebar Navigation (256px) */}
      <aside className="w-64 shrink-0 bg-white border-r border-slate-200 flex flex-col justify-between p-4">
        <div>
          <div className="px-2 py-2 mb-5">
            <span className="text-base font-bold tracking-tight text-slate-900 whitespace-nowrap">
              KnowledgeForge AI
            </span>
          </div>

          <div className="mb-6">
            <label htmlFor="org-switcher" className="block px-2 text-xs font-medium text-slate-500 mb-1.5">
              Active Organization
            </label>
            <div className="relative">
              <Building2 className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
              <select
                id="org-switcher"
                value={activeOrg.id}
                onChange={(e) => switchOrg(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm font-medium bg-slate-50 border border-slate-200 rounded-lg text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900"
              >
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="px-2 mt-1.5 text-xs text-slate-500">
              <span>Role: {activeOrg.role}</span>
              <span aria-hidden="true"> · </span>
              <span>Plan: {activeOrg.planTier}</span>
            </div>
          </div>

          <nav className="space-y-1">
            {navItems.map((item) => {
              const active = nav === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setNav(item.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm font-medium rounded-lg transition-colors whitespace-nowrap ${
                    active
                      ? "bg-slate-900 text-white"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="pt-4 border-t border-slate-200 px-2 text-xs text-slate-500 space-y-1">
          <div className="font-medium text-slate-700">Tenant Isolation Active</div>
          <div className="font-mono truncate">{activeOrg.id}</div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header Contract: Breadcrumb on left, 1 primary action on right */}
        <header className="h-16 bg-white border-b border-slate-200 px-8 flex items-center justify-between gap-8 shrink-0">
          <div className="flex items-center gap-2 text-sm min-w-0">
            <span className="text-slate-500 truncate">{activeOrg.name}</span>
            <span className="text-slate-300">/</span>
            <h1 className="font-semibold text-slate-900 truncate">{sectionTitles[nav]}</h1>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={() => setNav("knowledge-bases")}
              className="px-4 py-2 text-xs font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors whitespace-nowrap shrink-0"
            >
              Upload Document
            </button>
          </div>
        </header>

        <main className="flex-1 p-8 max-w-6xl w-full mx-auto">
          {nav === "chat" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
              {/* Chat Thread */}
              <section className="lg:col-span-2 bg-white border border-slate-200 rounded-xl flex flex-col min-h-[580px]">
                <div className="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs font-medium text-slate-600">
                    Scoped Knowledge Bases ({selectedKbIds.length} active)
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {orgKbs.map((kb) => {
                      const active = selectedKbIds.includes(kb.id);
                      return (
                        <button
                          key={kb.id}
                          onClick={() =>
                            setSelectedKbIds((prev) =>
                              active ? prev.filter((id) => id !== kb.id) : [...prev, kb.id]
                            )
                          }
                          className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap shrink-0 ${
                            active
                              ? "bg-slate-900 text-white border-slate-900"
                              : "bg-white text-slate-600 border-slate-200 hover:text-slate-900"
                          }`}
                        >
                          {kb.name}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="flex-1 p-6 space-y-5 overflow-y-auto">
                  {orgMessages.length === 0 ? (
                    <div className="py-16 text-center max-w-md mx-auto">
                      <p className="text-sm font-medium text-slate-900">
                        No messages yet in {activeOrg.name}
                      </p>
                      <p className="text-xs text-slate-500 mt-1.5">
                        Ask a question below to query {orgDocs.length} indexed document(s) via hybrid pgvector and full-text search.
                      </p>
                    </div>
                  ) : (
                    orgMessages.map((msg) => (
                      <div
                        key={msg.id}
                        className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
                      >
                        <div
                          className={`max-w-xl rounded-xl px-4 py-3 text-sm leading-relaxed ${
                            msg.role === "user"
                              ? "bg-slate-900 text-white"
                              : "bg-slate-50 border border-slate-200 text-slate-900"
                          }`}
                        >
                          <p>{msg.content}</p>
                          {msg.role === "assistant" && (
                            <div className="mt-3 pt-3 border-t border-slate-200 flex items-center justify-between gap-4 text-xs text-slate-500">
                              <span className="font-mono tabular-nums">
                                Confidence: {((msg.confidenceScore ?? 0) * 100).toFixed(0)}%
                                {msg.citations ? ` · ${msg.citations.length} citation(s)` : ""}
                              </span>
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() =>
                                    setChatHistory((prev) => ({
                                      ...prev,
                                      [activeOrg.id]: prev[activeOrg.id].map((m) =>
                                        m.id === msg.id ? { ...m, feedback: "up" } : m
                                      ),
                                    }))
                                  }
                                  className={`p-1.5 rounded hover:bg-slate-200 ${
                                    msg.feedback === "up" ? "text-emerald-600" : "text-slate-400"
                                  }`}
                                  aria-label="Helpful"
                                >
                                  <ThumbsUp className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={() =>
                                    setChatHistory((prev) => ({
                                      ...prev,
                                      [activeOrg.id]: prev[activeOrg.id].map((m) =>
                                        m.id === msg.id ? { ...m, feedback: "down" } : m
                                      ),
                                    }))
                                  }
                                  className={`p-1.5 rounded hover:bg-slate-200 ${
                                    msg.feedback === "down" ? "text-red-600" : "text-slate-400"
                                  }`}
                                  aria-label="Not helpful"
                                >
                                  <ThumbsDown className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          )}
                        </div>

                        {msg.citations && msg.citations.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {msg.citations.map((cit, i) => (
                              <button
                                key={cit.chunkId}
                                onClick={() => setActiveCitation(cit)}
                                className="text-xs px-2.5 py-1 bg-white border border-slate-200 rounded-md text-slate-700 hover:border-slate-400 transition-colors"
                              >
                                [{i + 1}] {cit.documentName} · p.{cit.pageNumber}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <form onSubmit={handleAsk} className="p-4 border-t border-slate-200 flex gap-3">
                  <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder={`Ask ${activeOrg.name} knowledge bases (e.g., "How many paid vacation days?" or "tenant isolation")`}
                    className="flex-1 px-4 py-2.5 text-sm bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2.5 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 inline-flex items-center gap-2 whitespace-nowrap shrink-0"
                  >
                    <Send className="w-4 h-4" />
                    <span>Ask</span>
                  </button>
                </form>
              </section>

              {/* Citation Inspector Panel */}
              <aside className="bg-white border border-slate-200 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-slate-900">Source Citation Inspector</h2>
                <p className="text-xs text-slate-500 mt-1 mb-4">
                  Click any citation below an answer to inspect the exact retrieved chunk.
                </p>

                {activeCitation ? (
                  <div className="space-y-3 pt-3 border-t border-slate-200">
                    <div>
                      <div className="text-sm font-medium text-slate-900 break-all">
                        {activeCitation.documentName}
                      </div>
                      <div className="text-xs text-slate-500 font-mono tabular-nums mt-1">
                        Page {activeCitation.pageNumber} · Relevance{" "}
                        {(activeCitation.relevanceScore * 100).toFixed(0)}%
                      </div>
                    </div>
                    <p className="text-xs leading-relaxed text-slate-700 bg-slate-50 p-3 rounded-lg border border-slate-200">
                      {activeCitation.excerpt}
                    </p>
                    <div className="text-xs text-slate-400 font-mono">
                      chunk_id: {activeCitation.chunkId}
                    </div>
                  </div>
                ) : (
                  <div className="py-10 text-center text-xs text-slate-400 border-t border-slate-200">
                    No citation selected
                  </div>
                )}
              </aside>
            </div>
          )}

          {nav === "knowledge-bases" && (
            <div className="space-y-6">
              {uploadNotice && (
                <div className="px-4 py-3 bg-white border border-slate-200 rounded-xl text-sm text-slate-700">
                  {uploadNotice}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <section className="bg-white border border-slate-200 rounded-xl p-6">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Create Knowledge Base</h2>
                  <form onSubmit={handleCreateKb} className="space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
                      <input
                        type="text"
                        value={newKbName}
                        onChange={(e) => setNewKbName(e.target.value)}
                        placeholder="Engineering Runbooks"
                        className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">LLM Model</label>
                      <select
                        value={newKbModel}
                        onChange={(e) => setNewKbModel(e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg"
                      >
                        <option value="gpt-4o-mini">OpenAI · gpt-4o-mini</option>
                        <option value="claude-3-5-sonnet">Anthropic · claude-3-5-sonnet</option>
                        <option value="llama3.1:8b">Ollama · llama3.1:8b</option>
                      </select>
                    </div>
                    <button
                      type="submit"
                      className="px-4 py-2 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800 inline-flex items-center gap-1.5"
                    >
                      <Plus className="w-4 h-4" />
                      <span>Create Knowledge Base</span>
                    </button>
                  </form>
                </section>

                <section className="bg-white border border-slate-200 rounded-xl p-6">
                  <h2 className="text-base font-semibold text-slate-900 mb-4">Upload & Ingest Document</h2>
                  <p className="text-xs text-slate-500 mb-4">
                    Files are SHA-256 checksummed for deduplication, normalized, and split into overlapping token-aware chunks.
                  </p>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Target Knowledge Base</label>
                      <select
                        value={targetKbForUpload}
                        onChange={(e) => setTargetKbForUpload(e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg"
                      >
                        {orgKbs.map((kb) => (
                          <option key={kb.id} value={kb.id}>
                            {kb.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <label className="flex items-center justify-center gap-2 px-4 py-6 border border-dashed border-slate-300 rounded-lg cursor-pointer hover:bg-slate-50 text-sm text-slate-600">
                      <Upload className="w-4 h-4" />
                      <span>Select TXT, Markdown, CSV, or JSON file to ingest</span>
                      <input type="file" accept=".txt,.md,.csv,.json" onChange={handleFileUpload} className="hidden" />
                    </label>
                  </div>
                </section>
              </div>

              {/* Documents Table */}
              <section className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                  <h2 className="text-base font-semibold text-slate-900">Indexed Documents</h2>
                  <span className="text-xs text-slate-500 font-mono tabular-nums">
                    {orgDocs.length} document(s)
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs text-slate-500 border-b border-slate-200">
                      <tr>
                        <th className="py-2.5 px-6 font-medium">Filename</th>
                        <th className="py-2.5 px-4 font-medium">Status</th>
                        <th className="py-2.5 px-4 font-medium">Checksum</th>
                        <th className="py-2.5 px-4 font-medium text-right">Chunks</th>
                        <th className="py-2.5 px-6 font-medium text-right">Size</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {orgDocs.map((doc) => (
                        <tr key={doc.id} className="hover:bg-slate-50">
                          <td className="py-3 px-6 font-medium text-slate-900 flex items-center gap-2">
                            <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                            <span>{doc.filename}</span>
                          </td>
                          <td className="py-3 px-4 text-emerald-700 text-xs font-medium capitalize">
                            {doc.status}
                          </td>
                          <td className="py-3 px-4 font-mono text-xs text-slate-500">{doc.checksum}</td>
                          <td className="py-3 px-4 text-right font-mono tabular-nums text-slate-700">
                            {doc.chunks.length}
                          </td>
                          <td className="py-3 px-6 text-right font-mono tabular-nums text-slate-500">
                            {(doc.sizeBytes / 1024).toFixed(1)} KB
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {nav === "team" && (
            <div className="space-y-6">
              <section className="bg-white border border-slate-200 rounded-xl p-6">
                <h2 className="text-base font-semibold text-slate-900 mb-4">Invite Organization Member</h2>
                <form onSubmit={handleInviteMember} className="flex flex-wrap gap-3">
                  <input
                    type="email"
                    required
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="colleague@company.com"
                    className="flex-1 min-w-56 px-3 py-2 text-sm border border-slate-200 rounded-lg"
                  />
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as Role)}
                    className="px-3 py-2 text-sm border border-slate-200 rounded-lg"
                  >
                    <option value="admin">Admin</option>
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                    <option value="billing_manager">Billing Manager</option>
                  </select>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800"
                  >
                    Send Invitation
                  </button>
                </form>
              </section>

              <section className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200">
                  <h2 className="text-base font-semibold text-slate-900">Members ({orgMembers.length})</h2>
                </div>
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500 border-b border-slate-200">
                    <tr>
                      <th className="py-2.5 px-6 font-medium">Name</th>
                      <th className="py-2.5 px-4 font-medium">Email</th>
                      <th className="py-2.5 px-4 font-medium">Role</th>
                      <th className="py-2.5 px-6 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {orgMembers.map((m) => (
                      <tr key={m.id}>
                        <td className="py-3 px-6 font-medium text-slate-900">{m.name}</td>
                        <td className="py-3 px-4 text-slate-600">{m.email}</td>
                        <td className="py-3 px-4">
                          <select
                            disabled={m.role === "owner"}
                            value={m.role}
                            onChange={(e) =>
                              setMembers((prev) =>
                                prev.map((row) =>
                                  row.id === m.id ? { ...row, role: e.target.value as Role } : row
                                )
                              )
                            }
                            className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white"
                          >
                            <option value="owner">owner</option>
                            <option value="admin">admin</option>
                            <option value="editor">editor</option>
                            <option value="viewer">viewer</option>
                            <option value="billing_manager">billing_manager</option>
                          </select>
                        </td>
                        <td className="py-3 px-6 text-right">
                          {m.role !== "owner" && (
                            <button
                              onClick={() => setMembers((prev) => prev.filter((row) => row.id !== m.id))}
                              className="text-slate-400 hover:text-red-600 p-1"
                              aria-label="Remove member"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          )}

          {nav === "analytics" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: "Knowledge Bases", value: orgKbs.length },
                  { label: "Indexed Documents", value: orgDocs.length },
                  {
                    label: "Vector Chunks",
                    value: orgDocs.reduce((acc, d) => acc + d.chunks.length, 0),
                  },
                  {
                    label: "Active Members",
                    value: orgMembers.length,
                  },
                ].map((stat) => (
                  <div key={stat.label} className="bg-white border border-slate-200 rounded-xl p-5">
                    <div className="text-xs text-slate-500">{stat.label}</div>
                    <div className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-1">
                      {stat.value}
                    </div>
                  </div>
                ))}
              </div>

              <section className="bg-white border border-slate-200 rounded-xl p-6">
                <h2 className="text-base font-semibold text-slate-900 mb-1">Programmatic API Keys</h2>
                <p className="text-xs text-slate-500 mb-4">
                  Keys are SHA-256 hashed at rest in PostgreSQL and revealed only once upon creation.
                </p>

                <form onSubmit={handleCreateApiKey} className="flex gap-3 mb-5">
                  <input
                    type="text"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="Key label (e.g., Docs CI Sync)"
                    className="flex-1 px-3 py-2 text-sm border border-slate-200 rounded-lg"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800 inline-flex items-center gap-1.5"
                  >
                    <Key className="w-3.5 h-3.5" />
                    <span>Generate API Key</span>
                  </button>
                </form>

                {revealedKey && (
                  <div className="mb-5 p-4 bg-slate-50 border border-slate-200 rounded-lg flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-slate-700">Copy key now (shown once):</div>
                      <div className="font-mono text-xs text-slate-900 truncate mt-1">{revealedKey}</div>
                    </div>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(revealedKey);
                        setCopiedKey(true);
                        setTimeout(() => setCopiedKey(false), 1500);
                      }}
                      className="px-3 py-1.5 bg-white border border-slate-200 rounded-md text-xs font-medium inline-flex items-center gap-1.5 shrink-0"
                    >
                      {copiedKey ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedKey ? "Copied" : "Copy"}</span>
                    </button>
                  </div>
                )}

                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500 border-b border-slate-200">
                    <tr>
                      <th className="py-2 px-4 font-medium">Name</th>
                      <th className="py-2 px-4 font-medium">Prefix</th>
                      <th className="py-2 px-4 font-medium text-right">Requests</th>
                      <th className="py-2 px-4 font-medium text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {orgKeys.map((k) => (
                      <tr key={k.id}>
                        <td className="py-2.5 px-4 font-medium text-slate-900">{k.name}</td>
                        <td className="py-2.5 px-4 font-mono text-xs text-slate-500">{k.prefix}...</td>
                        <td className="py-2.5 px-4 text-right font-mono tabular-nums">{k.requestCount}</td>
                        <td className="py-2.5 px-4 text-right">
                          {k.active ? (
                            <button
                              onClick={() =>
                                setApiKeys((prev) =>
                                  prev.map((row) => (row.id === k.id ? { ...row, active: false } : row))
                                )
                              }
                              className="text-xs text-red-600 hover:underline"
                            >
                              Revoke
                            </button>
                          ) : (
                            <span className="text-xs text-slate-400">Revoked</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          )}

          {nav === "billing" && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {PLAN_DETAILS.map((plan) => {
                const isCurrent = activeOrg.planTier === plan.tier;
                return (
                  <div
                    key={plan.tier}
                    className="bg-white border border-slate-200 rounded-xl p-5 flex flex-col justify-between"
                  >
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{plan.name}</div>
                      <div className="text-2xl font-semibold font-mono tabular-nums text-slate-900 mt-2">
                        ${plan.price}
                        <span className="text-xs font-sans font-normal text-slate-500">/mo</span>
                      </div>
                      <ul className="mt-4 space-y-2 text-xs text-slate-600 font-mono tabular-nums">
                        <li>{plan.docs.toLocaleString()} docs/mo</li>
                        <li>{plan.storageMb.toLocaleString()} MB storage</li>
                        <li>{plan.requests.toLocaleString()} AI requests</li>
                        <li>{plan.seats.toLocaleString()} team members</li>
                        <li>{plan.kbs.toLocaleString()} knowledge bases</li>
                      </ul>
                    </div>
                    <button
                      onClick={() => setPlan(plan.tier)}
                      disabled={isCurrent}
                      className={`mt-6 w-full py-2 px-3 rounded-lg text-xs font-medium transition-colors ${
                        isCurrent
                          ? "bg-slate-100 text-slate-500 cursor-default"
                          : "bg-slate-900 text-white hover:bg-slate-800"
                      }`}
                    >
                      {isCurrent ? "Current Plan" : `Switch to ${plan.name}`}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {nav === "api-docs" && (
            <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
              <div>
                <h2 className="text-base font-semibold text-slate-900">FastAPI Backend & Multi-Tenant Architecture</h2>
                <p className="text-sm text-slate-600 mt-1">
                  Full Python 3.12 backend located in <code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">backend/</code> with SQLAlchemy 2.0 async, Alembic, pgvector, Redis rate limiting, Celery ingestion workers, and Next.js scaffold in <code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">frontend/</code>.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Configured FastAPI Base URL</label>
                <input
                  type="text"
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  className="w-full max-w-md px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg"
                />
              </div>

              <div className="border-t border-slate-200 pt-4">
                <h3 className="text-sm font-semibold text-slate-900 mb-3">Core REST API Endpoints (/api/v1)</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs font-mono">
                  {[
                    "POST /auth/register · POST /auth/login · POST /auth/refresh",
                    "GET /organizations · POST /organizations · POST /organizations/{id}/invite",
                    "GET /knowledge-bases · POST /knowledge-bases · PUT /knowledge-bases/{id}/access",
                    "POST /knowledge-bases/{id}/documents/upload · POST /documents/{id}/reprocess",
                    "POST /chat/sessions · POST /chat/sessions/{id}/messages · GET /chat/sessions/{id}/stream",
                    "POST /chat/messages/{id}/feedback · GET /analytics/overview · POST /api-keys",
                  ].map((line) => (
                    <div key={line} className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-700">
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
