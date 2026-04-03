import React, { useMemo, useRef, useState } from "react";

export default function App() {
  const [apiBase, setApiBase] = useState("http://127.0.0.1:8000");
  const [meterId, setMeterId] = useState("");
  const [utility, setUtility] = useState("");
  const [file, setFile] = useState(null);

  const [status, setStatus] = useState("Pronto.");
  const [reading, setReading] = useState(null);
  const [history, setHistory] = useState([]);

  const fileInputRef = useRef(null);

  const wsBase = useMemo(() => {
    const base = apiBase.trim().replace(/\/+$/, "");
    return base.replace(/^http:\/\//, "ws://").replace(/^https:\/\//, "wss://");
  }, [apiBase]);

  function formatDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toLocaleDateString("pt-BR");
  }

  function normalizeValue(obj) {
    if (!obj) return null;
    const v = obj.value ?? obj.reading ?? obj.valor;
    return v === undefined || v === null || v === "" ? null : v;
  }

  async function fetchHistory(nextApiBase, nextMeterId) {
    try {
      const base = nextApiBase.trim().replace(/\/+$/, "");
      const r = await fetch(
        `${base}/api/readings?meter_id=${encodeURIComponent(nextMeterId)}`
      );
      if (!r.ok) return;
      const data = await r.json();
      if (Array.isArray(data?.items)) setHistory(data.items);
    } catch {
      // ignore
    }
  }

  function resetAll() {
    setMeterId("");
    setUtility("");
    setFile(null);
    setReading(null);
    setHistory([]);
    setStatus("Limpo.");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function onSend() {
    const base = apiBase.trim().replace(/\/+$/, "");
    if (!base || !meterId || !utility || !file) {
      setStatus("Preencha id_medidor, tipo e selecione a imagem.");
      return;
    }

    setStatus("Enviando…");

    const fd = new FormData();
    fd.append("meter_id", meterId);
    fd.append("utility", utility);
    fd.append("file", file);

    let jobId;
    try {
      const r = await fetch(`${base}/predict`, { method: "POST", body: fd });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.detail || r.statusText);
      jobId = data?.job_id;
      if (!jobId) throw new Error("API não retornou job_id.");
    } catch (e) {
      setStatus(`Erro: ${e?.message || e}`);
      return;
    }

    setStatus(`Job criado: ${jobId}\nAguardando resultado…`);

    try {
      const wsUrl = `${wsBase}/ws/jobs/${encodeURIComponent(jobId)}`;
      const ws = new WebSocket(wsUrl);

      ws.onmessage = async (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          msg = { status: "unknown", raw: ev.data };
        }

        if (msg.status === "done") {
          setReading(msg.reading);
          setStatus("Leitura recebida ✅");
          ws.close();
          await fetchHistory(base, meterId);
        } else if (msg.status === "timeout") {
          setStatus("Timeout aguardando leitura. Verifique se o worker está rodando.");
          ws.close();
        } else {
          setStatus(JSON.stringify(msg, null, 2));
        }
      };

      ws.onerror = () => {
        setStatus("Erro no WebSocket. Verifique se a API expõe /ws/jobs/{job_id}.");
      };
    } catch (e) {
      setStatus(`Erro: ${e?.message || e}`);
    }
  }

  const value = normalizeValue(reading);
  const unitText = reading?.unit || reading?.utility || "m";

  return (
    <div className="min-h-screen bg-[#ffffff] p-4 md:p-6">
      <div className="mx-auto flex h-[min(760px,96vh)] w-[min(1400px,98vw)] overflow-hidden rounded-[26px] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
        {/* Sidebar */}
        <aside className="w-[320px] bg-[#f2c230] px-6 py-7 text-white">
          <div className="flex items-center justify-center border-b-2 border-white/40 pb-6">
            <img
              src="/UFG_branco.png"
              alt="UFG"
              className="h-auto w-[240px] object-contain"
            />
          </div>

          <nav className="mt-10 flex flex-col gap-6 px-1">
            <a
              href="#"
              className="rounded-xl px-3 py-4 text-[34px] font-light tracking-wide hover:bg-white/10"
            >
              Painel Geral
            </a>
            <a
              href="#"
              className="rounded-xl px-3 py-4 text-[34px] font-light tracking-wide hover:bg-white/10"
            >
              Histórico
            </a>
          </nav>
        </aside>

        {/* Main */}
        <main className="flex flex-1 gap-8 bg-[#0e6ea8] p-8">
          {/* Left */}
          <section className="flex flex-1 flex-col gap-6">
            <div className="flex flex-col gap-2">
              <div className="text-[40px] font-light tracking-wide text-white">
                Título
              </div>
              <input
                value={meterId}
                onChange={(e) => setMeterId(e.target.value)}
                placeholder="id_medidor"
                className="h-11 rounded-lg bg-white px-4 text-[15px] text-gray-900 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.06)] outline-none placeholder:text-gray-400"
              />
            </div>

            <div className="flex flex-col gap-2">
              <div className="text-[40px] font-light tracking-wide text-white">
                Tipo
              </div>
              <select
                value={utility}
                onChange={(e) => setUtility(e.target.value)}
                className="h-11 rounded-lg bg-white px-4 text-[15px] text-gray-900 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.06)] outline-none"
              >
                <option value="" disabled>
                  energia, água, gás
                </option>
                <option value="power">energia</option>
                <option value="water">água</option>
                <option value="gas">gás</option>
              </select>
            </div>

            <div className="mt-2 text-[40px] font-light tracking-wide text-white">
              Submeter a leitura
            </div>

            <div className="relative h-[380px] rounded-xl bg-[#f2f3f5] p-5 text-gray-500 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.06)]">
              <div className="flex items-center gap-4 text-[#f2c230]">
                <span title="upload">⤴</span>
                <span title="anexar">📎</span>
                <span title="câmera">📷</span>
              </div>

              <div className="flex h-[calc(100%-40px)] flex-col items-center justify-center gap-4">
                <div className="flex h-[72px] w-[72px] items-center justify-center rounded-xl bg-[#f2c230] shadow-[0_8px_20px_rgba(0,0,0,0.12)]">
                  <svg
                    width="34"
                    height="28"
                    viewBox="0 0 24 18"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className="opacity-90"
                  >
                    <path
                      d="M3 2C1.895 2 1 2.895 1 4V14C1 15.105 1.895 16 3 16H21C22.105 16 23 15.105 23 14V4C23 2.895 22.105 2 21 2H3Z"
                      stroke="#111827"
                      strokeWidth="1.4"
                    />
                    <path
                      d="M4 13L9 8L13 12L16 9L20 13"
                      stroke="#111827"
                      strokeWidth="1.4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>

                <div className="text-sm tracking-wide">insira a imagem</div>

                {file ? (
                  <div className="text-xs text-gray-600">{file.name}</div>
                ) : null}
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  setFile(f);
                  if (f) setStatus(`Imagem selecionada: ${f.name}`);
                }}
                className="absolute inset-0 cursor-pointer opacity-0"
              />
            </div>

            <div className="mt-2 flex items-center gap-3">
              <button
                onClick={onSend}
                className="h-11 rounded-xl bg-[#f2c230] px-5 font-bold text-gray-900 shadow-[0_10px_30px_rgba(0,0,0,0.12)]"
              >
                Enviar
              </button>

              <button
                onClick={resetAll}
                className="h-11 rounded-xl border border-white/25 bg-white/10 px-5 font-bold text-white"
              >
                Limpar
              </button>

              <input
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
                className="h-11 w-[360px] rounded-xl bg-white px-4 text-[14px] text-gray-900 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.06)] outline-none"
              />
            </div>
          </section>

          {/* Right */}
          <aside className="w-[460px] rounded-xl bg-[#f2f3f5] p-7 text-gray-900 shadow-[inset_0_0_0_1px_rgba(0,0,0,0.06)]">
            <div className="text-[46px] font-normal tracking-wide text-gray-600">
              Valor lido
            </div>

            <div className="mt-4 flex items-end justify-between gap-4 pb-3">
              <div className="text-[42px] font-medium tracking-wide text-gray-800">
                {value === null ? "—" : String(value)}
              </div>

              <div className="flex items-center gap-2 pb-2 text-sm text-gray-500">
                <span>{unitText}</span>
                <span
                  className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-[4px] bg-[#f2c230] font-black text-gray-900 ${
                    value === null ? "opacity-30" : "opacity-100"
                  }`}
                >
                  ✓
                </span>
              </div>
            </div>

            <div className="my-4 h-px bg-gray-900/15" />

            <div className="text-[46px] font-normal tracking-wide text-gray-600">
              Leitura anteriores
            </div>

            <table className="mt-5 w-full border-collapse text-sm text-gray-700">
              <thead>
                <tr className="border-b border-gray-900/15 text-gray-500">
                  <th className="py-2 text-left font-semibold">data</th>
                  <th className="py-2 text-right font-semibold">valor</th>
                </tr>
              </thead>
              <tbody>
                {history.length ? (
                  history.slice(0, 5).map((it, idx) => {
                    const hv = it?.value ?? it?.reading ?? "—";
                    return (
                      <tr
                        key={idx}
                        className="border-b border-dashed border-gray-900/10"
                      >
                        <td className="py-3">{formatDate(it?.timestamp)}</td>
                        <td className="py-3 text-right">{String(hv)}</td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td className="py-3 text-gray-400">—</td>
                    <td className="py-3 text-right text-gray-400">—</td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className="mt-8 whitespace-pre-wrap rounded-xl bg-black/5 p-3 text-xs text-gray-500">
              {status}
            </div>
          </aside>
        </main>
      </div>
    </div>
  );
}