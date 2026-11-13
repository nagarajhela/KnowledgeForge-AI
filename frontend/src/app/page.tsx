"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface Org {
  id: string;
  name: string;
  role: string;
}

interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  llm_model: string;
}

interface Citation {
  document_id: string;
  document_name: string;
  chunk_id: string;
  page_number: number | null;
  excerpt: string;
  relevance_score: number;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  confidence_score?: number | null;
}

export default function WorkspacePage() {
  const [token, setToken] = useState<string | null>(null);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [activeOrgId, setActiveOrgId] = useState<string>("");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string>("");
  const [newKbName, setNewKbName] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("kf_access_token");
    setToken(t);
    if (!t) return;
    apiFetch<Org[]>("/organizations", { token: t })
      .then((list: Org[]) => {
        setOrgs(list);
        if (list.length > 0) {
          const saved = localStorage.getItem("kf_org_id") || list[0].id;
          setActiveOrgId(saved);
          localStorage.setItem("kf_org_id", saved);
        }
      })
      .catch((err: Error) => setStatusMsg(err.message));
  }, []);

  useEffect(() => {
    if (!token || !activeOrgId) return;
    apiFetch<{ items: KnowledgeBase[] }>("/knowledge-bases", {
      token,
      organizationId: activeOrgId,
    })
      .then((res: { items: KnowledgeBase[] }) => {
        setKbs(res.items);
        if (res.items.length > 0 && !selectedKbId) {
          setSelectedKbId(res.items[0].id);
        }
      })
      .catch((err: Error) => setStatusMsg(err.message));
  }, [token, activeOrgId, selectedKbId]);

  async function createKb(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !activeOrgId || !newKbName.trim()) return;
    const kb = await apiFetch<KnowledgeBase>("/knowledge-bases", {
      method: "POST",
      token,
      organizationId: activeOrgId,
      body: JSON.stringify({ name: newKbName.trim() }),
    });
    setKbs((prev) => [kb, ...prev]);
    setSelectedKbId(kb.id);
    setNewKbName("");
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !token || !activeOrgId || !selectedKbId) return;
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch<{ document: { filename: string; processing_status: string } }>(
      `/knowledge-bases/${selectedKbId}/documents/upload`,
      { method: "POST", token, organizationId: activeOrgId, body: form }
    );
    setStatusMsg(`Uploaded ${res.document.filename} (${res.document.processing_status})`);
  }

  async function askQuestion(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !activeOrgId || !selectedKbId || !question.trim()) return;
    let sid = sessionId;
    if (!sid) {
      const sess = await apiFetch<{ id: string }>("/chat/sessions", {
        method: "POST",
        token,
        organizationId: activeOrgId,
        body: JSON.stringify({ title: question.slice(0, 60), knowledge_base_ids: [selectedKbId] }),
      });
      sid = sess.id;
      setSessionId(sid);
    }
    const q = question;
    setQuestion("");
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", content: q }]);

    const ans = await apiFetch<{
      message_id: string;
      answer: string;
      citations: Citation[];
      confidence_score: number;
    }>(`/chat/sessions/${sid}/messages`, {
      method: "POST",
      token,
      organizationId: activeOrgId,
      body: JSON.stringify({ question: q }),
    });

    setMessages((prev) => [
      ...prev,
      {
        id: ans.message_id,
        role: "assistant",
        content: ans.answer,
        citations: ans.citations,
        confidence_score: ans.confidence_score,
      },
    ]);
  }

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-64 bg-white border-r border-slate-200 p-5 flex flex-col justify-between">
        <div>
          <div className="text-base font-semibold text-slate-900 mb-6">KnowledgeForge AI</div>
          <label className="block text-xs font-medium text-slate-500 mb-1">Active Organization</label>
          <select
            value={activeOrgId}
            onChange={(e) => {
              setActiveOrgId(e.target.value);
              localStorage.setItem("kf_org_id", e.target.value);
            }}
            className="w-full px-2.5 py-2 text-sm border border-slate-200 rounded-lg mb-6"
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} ({o.role})
              </option>
            ))}
          </select>

          <nav className="space-y-1 text-sm">
            <Link href="/" className="block px-3 py-2 rounded-lg bg-slate-100 font-medium text-slate-900">
              RAG Workspace
            </Link>
            <Link href="/billing" className="block px-3 py-2 rounded-lg text-slate-600 hover:bg-slate-50">
              Billing & Quotas
            </Link>
            <Link href="/login" className="block px-3 py-2 rounded-lg text-slate-600 hover:bg-slate-50">
              Sign In / Switch User
            </Link>
          </nav>
        </div>
        <div className="text-xs text-slate-400">Tenant-Isolated RAG</div>
      </aside>

      <main className="flex-1 p-8 max-w-5xl">
        {!token ? (
          <div className="bg-white border border-slate-200 rounded-xl p-8">
            <h1 className="text-xl font-semibold text-slate-900">Sign in required</h1>
            <p className="text-sm text-slate-600 mt-2 mb-4">
              Authenticate with your KnowledgeForge AI account to manage knowledge bases and query documents.
            </p>
            <Link
              href="/login"
              className="inline-block px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg"
            >
              Go to Login
            </Link>
          </div>
        ) : (
          <div className="space-y-6">
            {statusMsg && (
              <div className="px-4 py-2.5 bg-white border border-slate-200 rounded-lg text-sm text-slate-700">
                {statusMsg}
              </div>
            )}

            <section className="bg-white border border-slate-200 rounded-xl p-6">
              <h2 className="text-base font-semibold text-slate-900 mb-4">Knowledge Bases & Document Upload</h2>
              <div className="flex flex-wrap gap-3 items-center">
                <select
                  value={selectedKbId}
                  onChange={(e) => setSelectedKbId(e.target.value)}
                  className="px-3 py-2 border border-slate-200 rounded-lg text-sm"
                >
                  {kbs.map((kb) => (
                    <option key={kb.id} value={kb.id}>
                      {kb.name} ({kb.llm_model})
                    </option>
                  ))}
                </select>

                <label className="px-4 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg cursor-pointer">
                  Upload Document
                  <input type="file" onChange={handleUpload} className="hidden" />
                </label>

                <form onSubmit={createKb} className="flex gap-2 ml-auto">
                  <input
                    type="text"
                    value={newKbName}
                    onChange={(e) => setNewKbName(e.target.value)}
                    placeholder="New KB name"
                    className="px-3 py-2 border border-slate-200 rounded-lg text-sm"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2 border border-slate-200 rounded-lg text-sm font-medium hover:bg-slate-50"
                  >
                    Create KB
                  </button>
                </form>
              </div>
            </section>

            <section className="bg-white border border-slate-200 rounded-xl p-6">
              <h2 className="text-base font-semibold text-slate-900 mb-4">Grounded AI Chat</h2>
              <div className="space-y-4 mb-6 min-h-48">
                {messages.map((m) => (
                  <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
                    <div
                      className={`inline-block max-w-2xl px-4 py-3 rounded-xl text-sm ${
                        m.role === "user"
                          ? "bg-slate-900 text-white"
                          : "bg-slate-50 border border-slate-200 text-slate-900"
                      }`}
                    >
                      <p>{m.content}</p>
                      {m.citations && m.citations.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-slate-200 space-y-1 text-xs text-slate-600">
                          {m.citations.map((c, idx) => (
                            <div key={c.chunk_id}>
                              [{idx + 1}] {c.document_name}
                              {c.page_number ? ` · Page ${c.page_number}` : ""} · Relevance{" "}
                              <span className="font-mono tabular-nums">{(c.relevance_score * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <form onSubmit={askQuestion} className="flex gap-3">
                <input
                  type="text"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask a question across your permitted knowledge bases..."
                  className="flex-1 px-4 py-2.5 border border-slate-200 rounded-lg text-sm"
                />
                <button
                  type="submit"
                  className="px-5 py-2.5 bg-slate-900 text-white text-sm font-medium rounded-lg"
                >
                  Ask
                </button>
              </form>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
