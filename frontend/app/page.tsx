"use client";

import { useState, useRef, useEffect, FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { useQuery, Citation } from "@/lib/useQuery";
import { CitationCard } from "@/components/CitationCard";
import { StatusIndicator } from "@/components/StatusIndicator";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

const SUGGESTED = [
  "What does Section 17 of the Evidence Act say about admissions?",
  "Which Acts govern personal data protection in Malaysia?",
  "What are the penalties under the Penal Code for theft?",
];

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const { submit, status, response, citations, isLoading, error } = useQuery();

  useEffect(() => {
    if (!response) return;
    setMessages(prev => {
      const last = prev[prev.length - 1];
      if (last?.role === "assistant" && last.content === "") {
        return [...prev.slice(0, -1), { role: "assistant", content: response, citations }];
      }
      return prev;
    });
  }, [response, citations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const query = input.trim();
    if (!query || isLoading) return;
    setInput("");
    setMessages(prev => [
      ...prev,
      { role: "user", content: query },
      { role: "assistant", content: "" },
    ]);
    await submit(query);
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50">

      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-4 py-6 space-y-6 max-w-3xl mx-auto w-full">
        {messages.length === 0 && (
          <div className="text-center py-16 text-slate-400">
            <div className="text-5xl mb-3">⚖️</div>
            <p className="font-semibold text-slate-700 text-lg">Malaysian Legal Research</p>
            <p className="text-sm mt-1 mb-8">Ask about legislation, sections, or legal topics.</p>
            <div className="space-y-2 max-w-md mx-auto text-left">
              {SUGGESTED.map(q => (
                <button key={q} onClick={() => setInput(q)}
                  className="w-full text-sm text-slate-500 border border-slate-200 rounded-lg px-3 py-2.5 hover:bg-white hover:text-slate-700 transition-colors text-left">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "user" ? (
              <div className="max-w-xl bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-2xl w-full space-y-3">
                {msg.content ? (
                  <>
                    <div className="bg-white rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm border border-slate-100 text-sm text-slate-800 leading-relaxed prose prose-sm max-w-none prose-headings:text-slate-800">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="flex flex-wrap gap-2 px-1">
                        {msg.citations.map((c, j) => <CitationCard key={j} citation={c} />)}
                      </div>
                    )}
                  </>
                ) : (
                  isLoading && i === messages.length - 1 && <StatusIndicator message={status} />
                )}
                {error && i === messages.length - 1 && (
                  <p className="text-sm text-red-500 px-1">{error}</p>
                )}
              </div>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
      </main>

      {/* Disclaimer */}
      <div className="bg-amber-50 border-t border-amber-200 px-4 py-2 text-center text-xs text-amber-700">
        For legal research only. This tool does not provide legal advice — consult a qualified Malaysian lawyer for your specific situation.
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white px-4 py-4">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex gap-3">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about Malaysian legislation..."
            disabled={isLoading}
            className="flex-1 rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-50 bg-slate-50"
          />
          <button type="submit" disabled={isLoading || !input.trim()}
            className="px-5 py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {isLoading ? "..." : "Ask"}
          </button>
        </form>
      </div>
    </div>
  );
}
