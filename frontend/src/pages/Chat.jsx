import { useEffect, useRef, useState } from "react";
import { Send, Bot, User, FileText, AlertTriangle, Trash2, RotateCw } from "lucide-react";
import { sendChatMessage, getChatHistory, clearChatHistory } from "../services/api";
import NeedPatient from "../components/NeedPatient";

/**
 * AI Health Assistant. Answers come only from the patient's records; each fact carries a [S#] citation that links
 * to the original document. History is stored per patient on the server.
 */

const DISCLAIMER =
  "Answers come only from the uploaded records and can contain mistakes. This is not medical advice: check anything " +
  "important against the original document and ask a clinician before making health decisions.";

/** Render text with [S#] markers as clickable citation chips. */
function Cited({ text, sources }) {
  const byRef = Object.fromEntries((sources || []).map((s) => [s.ref, s]));
  return text.split(/(\[S\d+\])/g).map((part, i) => {
    const m = part.match(/^\[(S\d+)\]$/);
    if (!m) return <span key={i}>{part}</span>;
    const s = byRef[m[1]];
    return s ? (
      <a key={i} className="cite" href={`/api/documents/${s.document_id}/file`} target="_blank" rel="noreferrer"
         title={s.label}>{m[1].slice(1)}</a>
    ) : null;
  });
}

function Message({ msg, onRetry }) {
  return (
    <div className={`chat-msg ${msg.role}`}>
      {msg.role === "assistant" ? <Bot size={20} /> : <User size={20} />}
      <div className={`chat-bubble ${msg.error ? "chat-error" : ""}`}>
        {msg.error ? (
          <>
            <AlertTriangle size={14} /> {msg.content}{" "}
            <button className="link-btn" onClick={onRetry}><RotateCw size={12} /> Retry</button>
          </>
        ) : msg.role === "assistant" ? (
          <>
            <div className="chat-text"><Cited text={msg.content} sources={msg.sources} /></div>
            {msg.sources?.length > 0 && (
              <ul className="chat-sources">
                {msg.sources.map((s) => (
                  <li key={s.ref}>
                    <a href={`/api/documents/${s.document_id}/file`} target="_blank" rel="noreferrer">
                      <FileText size={12} /> <span className="cite">{s.ref.slice(1)}</span> {s.label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          msg.content
        )}
      </div>
    </div>
  );
}

function ChatPanel({ patient }) {
  const first = patient.name.split(" ")[0];
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [booting, setBooting] = useState(true);
  const bottomRef = useRef();

  useEffect(() => {
    getChatHistory(patient.id)
      .then((r) => setMessages(r.data.map((m) => ({ role: m.role, content: m.content, sources: m.sources }))))
      .catch(() => {})
      .finally(() => setBooting(false));
  }, [patient.id]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  const ask = async (text) => {
    const q = text.trim();
    if (!q || loading) return;
    setInput("");
    setMessages((prev) => [...prev.filter((m) => !m.error), { role: "user", content: q }]);
    setLoading(true);
    try {
      const res = await sendChatMessage(patient.id, q);
      setMessages((prev) => [...prev, { role: "assistant", content: res.data.reply, sources: res.data.sources }]);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setMessages((prev) => [...prev, {
        role: "assistant", error: true, retry: q,
        content: typeof detail === "string" ? detail : "Could not reach the assistant.",
      }]);
    } finally {
      setLoading(false);
    }
  };

  const retry = () => {
    const last = [...messages].reverse().find((m) => m.error);
    if (last) {
      // the failed question was never saved on the server, so drop the optimistic copy and ask again
      setMessages((prev) => prev.slice(0, prev.lastIndexOf(last) - 1));
      ask(last.retry);
    }
  };

  const clear = async () => {
    if (!window.confirm("Delete this conversation? This cannot be undone.")) return;
    await clearChatHistory(patient.id);
    setMessages([]);
  };

  const suggestions = [
    `What medications is ${first} currently taking?`,
    "Which lab results are out of range?",
    "How have the lab results changed over time?",
    "Summarize the most recent hospital visit",
    "Are there any known allergies?",
    "When are the next follow-ups?",
  ];

  return (
    <div className="page chat-page">
      <div className="page-header">
        <h2>AI Health Assistant</h2>
        {messages.length > 0 && <button className="btn btn-outline" onClick={clear}><Trash2 size={14} /> Clear chat</button>}
      </div>
      <p className="chat-disclaimer"><AlertTriangle size={14} /> {DISCLAIMER}</p>

      <div className="chat-container">
        <div className="chat-messages">
          {!booting && messages.length === 0 && (
            <div className="chat-msg assistant">
              <Bot size={20} />
              <div className="chat-bubble">
                Hello! Ask me about {first}'s medications, lab results, visits or allergies. I only use the records
                that have been uploaded, and I show which document each answer comes from.
              </div>
            </div>
          )}
          {messages.map((msg, i) => <Message key={i} msg={msg} onRetry={retry} />)}
          {loading && (
            <div className="chat-msg assistant">
              <Bot size={20} />
              <div className="chat-bubble typing">Reading the records…</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="chat-input-bar">
          <input type="text" className="input" maxLength={2000} placeholder={`Ask about ${first}'s health records…`}
                 aria-label="Your question" value={input} onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && ask(input)} />
          <button className="btn btn-primary" onClick={() => ask(input)} disabled={loading || !input.trim()} aria-label="Send">
            <Send size={18} />
          </button>
        </div>

        <div className="suggested-questions">
          {suggestions.map((q) => (
            <button key={q} className="btn btn-outline" disabled={loading} onClick={() => ask(q)}>{q}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Chat() {
  return <NeedPatient>{(p) => <ChatPanel key={p.id} patient={p} />}</NeedPatient>;
}
