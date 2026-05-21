import React, { useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_API = "http://127.0.0.1:8000";

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API);
  const [auth, setAuth] = useState(null); // { role: "user" | "company", name, meterId }
  const [loginRole, setLoginRole] = useState("user");
  const [loginName, setLoginName] = useState("");
  const [loginMeterId, setLoginMeterId] = useState("");

  const [meterId, setMeterId] = useState("");
  const [utility, setUtility] = useState("water");
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("Pronto.");
  const [reading, setReading] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyFilter, setHistoryFilter] = useState("");

  const fileInputRef = useRef(null);

  const cleanApiBase = useMemo(() => apiBase.trim().replace(/\/+$/, ""), [apiBase]);
  const wsBase = useMemo(
    () => cleanApiBase.replace(/^http:\/\//, "ws://").replace(/^https:\/\//, "wss://"),
    [cleanApiBase]
  );

  function formatDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
    return d.toLocaleString("pt-BR");
  }

  function normalizeValue(obj) {
    if (!obj) return null;
    const v = obj.value ?? obj.reading ?? obj.valor;
    return v === undefined || v === null || v === "" ? null : v;
  }

  async function fetchHistory(filterMeterId = "") {
    try {
      setStatus("Carregando histórico...");
      const query = filterMeterId ? `?meter_id=${encodeURIComponent(filterMeterId)}` : "";
      const response = await fetch(`${cleanApiBase}/api/readings${query}`);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data?.detail || "Erro ao buscar histórico");
      }

      setHistory(Array.isArray(data?.items) ? data.items : []);
      setStatus("Histórico atualizado.");
    } catch (error) {
      setStatus(`Erro ao carregar histórico: ${error?.message || error}`);
    }
  }

  useEffect(() => {
    if (!auth) return;

    if (auth.role === "user") {
      setMeterId(auth.meterId || "");
      setHistoryFilter(auth.meterId || "");
      fetchHistory(auth.meterId || "");
    } else {
      setMeterId("");
      setHistoryFilter("");
      fetchHistory("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth]);

  function handleLogin(e) {
    e.preventDefault();

    if (!loginName.trim()) {
      setStatus("Informe o nome para entrar.");
      return;
    }

    if (loginRole === "user" && !loginMeterId.trim()) {
      setStatus("Informe o código do medidor do usuário local.");
      return;
    }

    setAuth({
      role: loginRole,
      name: loginName.trim(),
      meterId: loginRole === "user" ? loginMeterId.trim() : "",
    });
  }

  function logout() {
    setAuth(null);
    setLoginName("");
    setLoginMeterId("");
    setReading(null);
    setHistory([]);
    setStatus("Sessão encerrada.");
  }

  function resetForm() {
    setUtility("water");
    setFile(null);
    setReading(null);
    setStatus("Formulário limpo.");
    if (auth?.role === "company") setMeterId("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function onSend() {
    if (!meterId.trim() || !utility || !file) {
      setStatus("Preencha o medidor, o tipo e selecione uma imagem.");
      return;
    }

    setStatus("Enviando imagem...");

    const formData = new FormData();
    formData.append("meter_id", meterId.trim());
    formData.append("utility", utility);
    formData.append("file", file);

    let jobId = "";

    try {
      const response = await fetch(`${cleanApiBase}/api/uploads`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data?.detail || "Erro ao enviar imagem");
      }

      jobId = data?.job_id;
      setReading(data);
      setStatus(`Imagem enviada. Job: ${jobId || "sem job_id"}. Aguardando worker...`);
    } catch (error) {
      setStatus(`Erro no envio: ${error?.message || error}`);
      return;
    }

    if (!jobId) {
      await fetchHistory(auth?.role === "user" ? auth.meterId : historyFilter);
      return;
    }

    try {
      const ws = new WebSocket(`${wsBase}/ws/jobs/${encodeURIComponent(jobId)}`);

      ws.onmessage = async (event) => {
        const message = JSON.parse(event.data);

        if (message.status === "done") {
          setReading(message.reading);
          setStatus("Leitura recebida e salva no banco.");
          ws.close();
          await fetchHistory(auth?.role === "user" ? auth.meterId : historyFilter);
        }

        if (message.status === "timeout") {
          setStatus("A leitura ainda não foi salva. Verifique se o worker está rodando.");
          ws.close();
          await fetchHistory(auth?.role === "user" ? auth.meterId : historyFilter);
        }
      };

      ws.onerror = async () => {
        setStatus("Não foi possível acompanhar pelo WebSocket. Atualize o histórico manualmente.");
        await fetchHistory(auth?.role === "user" ? auth.meterId : historyFilter);
      };
    } catch {
      await fetchHistory(auth?.role === "user" ? auth.meterId : historyFilter);
    }
  }

  if (!auth) {
    return (
      <div className="min-h-screen bg-[#0e6ea8] p-4 md:p-8">
        <div className="mx-auto grid min-h-[720px] max-w-[1180px] overflow-hidden rounded-[26px] bg-white shadow-[0_10px_30px_rgba(0,0,0,0.18)] md:grid-cols-[360px_1fr]">
          <aside className="bg-[#f2c230] px-8 py-10 text-white">
            <img src="/UFG_branco.png" alt="UFG" className="w-[250px]" />
            <div className="mt-10 h-px bg-white/50" />
            <h1 className="mt-10 text-[42px] font-light leading-tight">Sistema de leitura de medidores</h1>
            <p className="mt-6 text-lg text-white/90">Acesso para concessionária ou usuário local.</p>
          </aside>

          <main className="flex items-center justify-center bg-[#f2f3f5] p-8">
            <form onSubmit={handleLogin} className="w-full max-w-[520px] rounded-2xl bg-white p-8 shadow-[0_10px_30px_rgba(0,0,0,0.10)]">
              <h2 className="text-[42px] font-light text-gray-700">Login</h2>
              <p className="mt-2 text-gray-500">Escolha o tipo de acesso para abrir a página correta.</p>

              <div className="mt-8 grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setLoginRole("user")}
                  className={`rounded-xl px-4 py-4 font-bold ${loginRole === "user" ? "bg-[#f2c230] text-gray-900" : "bg-gray-100 text-gray-600"}`}
                >
                  Usuário local
                </button>
                <button
                  type="button"
                  onClick={() => setLoginRole("company")}
                  className={`rounded-xl px-4 py-4 font-bold ${loginRole === "company" ? "bg-[#f2c230] text-gray-900" : "bg-gray-100 text-gray-600"}`}
                >
                  Concessionária
                </button>
              </div>

              <label className="mt-6 block text-sm font-semibold text-gray-500">Nome</label>
              <input
                value={loginName}
                onChange={(e) => setLoginName(e.target.value)}
                placeholder="Digite seu nome"
                className="mt-2 h-12 w-full rounded-xl border border-gray-200 px-4 outline-none focus:border-[#0e6ea8]"
              />

              {loginRole === "user" && (
                <>
                  <label className="mt-5 block text-sm font-semibold text-gray-500">Código do medidor</label>
                  <input
                    value={loginMeterId}
                    onChange={(e) => setLoginMeterId(e.target.value)}
                    placeholder="Ex.: testebd"
                    className="mt-2 h-12 w-full rounded-xl border border-gray-200 px-4 outline-none focus:border-[#0e6ea8]"
                  />
                </>
              )}

              <label className="mt-5 block text-sm font-semibold text-gray-500">Endereço da API</label>
              <input
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
                className="mt-2 h-12 w-full rounded-xl border border-gray-200 px-4 outline-none focus:border-[#0e6ea8]"
              />

              <button type="submit" className="mt-8 h-12 w-full rounded-xl bg-[#0e6ea8] font-bold text-white">
                Entrar
              </button>

              <div className="mt-5 rounded-xl bg-gray-100 p-3 text-xs text-gray-500">{status}</div>
            </form>
          </main>
        </div>
      </div>
    );
  }

  const value = normalizeValue(reading);
  const unitText = reading?.unit || (utility === "power" ? "kWh" : "m3");
  const isCompany = auth.role === "company";

  return (
    <div className="min-h-screen bg-white p-4 md:p-6">
      <div className="mx-auto flex min-h-[760px] w-[min(1400px,98vw)] overflow-hidden rounded-[26px] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
        <aside className="w-[320px] bg-[#f2c230] px-6 py-7 text-white">
          <div className="flex items-center justify-center border-b-2 border-white/40 pb-6">
            <img src="/UFG_branco.png" alt="UFG" className="h-auto w-[240px] object-contain" />
          </div>

          <nav className="mt-10 flex flex-col gap-5 px-1">
            <div className="rounded-xl px-3 py-4 text-[30px] font-light tracking-wide hover:bg-white/10">Painel Geral</div>
            <div className="rounded-xl px-3 py-4 text-[30px] font-light tracking-wide hover:bg-white/10">Histórico</div>
            <div className="rounded-xl bg-white/10 px-3 py-4 text-sm">
              <strong>{isCompany ? "Concessionária" : "Usuário local"}</strong>
              <br />
              {auth.name}
            </div>
            <button onClick={logout} className="mt-4 rounded-xl border border-white/40 px-4 py-3 text-left font-bold text-white">
              Sair
            </button>
          </nav>
        </aside>

        <main className="flex flex-1 gap-8 bg-[#0e6ea8] p-8">
          <section className="flex flex-1 flex-col gap-6">
            <div className="text-[38px] font-light tracking-wide text-white">
              {isCompany ? "Painel da concessionária" : "Painel do usuário local"}
            </div>

            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <div>
                <label className="text-[30px] font-light text-white">Medidor</label>
                <input
                  value={meterId}
                  onChange={(e) => setMeterId(e.target.value)}
                  readOnly={!isCompany}
                  className="mt-2 h-11 w-full rounded-lg bg-white px-4 text-[15px] text-gray-900 outline-none disabled:opacity-80"
                />
              </div>

              <div>
                <label className="text-[30px] font-light text-white">Tipo</label>
                <select
                  value={utility}
                  onChange={(e) => setUtility(e.target.value)}
                  className="mt-2 h-11 w-full rounded-lg bg-white px-4 text-[15px] text-gray-900 outline-none"
                >
                  <option value="water">água</option>
                  <option value="power">energia</option>
                  <option value="gas">gás</option>
                </select>
              </div>
            </div>

            <div className="mt-2 text-[40px] font-light tracking-wide text-white">Submeter a leitura</div>

            <div className="relative h-[260px] rounded-xl bg-[#f2f3f5] p-5 text-gray-500">
              <div className="flex h-full flex-col items-center justify-center gap-4">
                <div className="flex h-[72px] w-[72px] items-center justify-center rounded-xl bg-[#f2c230] text-3xl">▧</div>
                <div className="text-sm tracking-wide">insira a imagem</div>
                {file ? <div className="text-xs text-gray-600">{file.name}</div> : null}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const selected = e.target.files?.[0] || null;
                  setFile(selected);
                  if (selected) setStatus(`Imagem selecionada: ${selected.name}`);
                }}
                className="absolute inset-0 cursor-pointer opacity-0"
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button onClick={onSend} className="h-11 rounded-xl bg-[#f2c230] px-5 font-bold text-gray-900">
                Enviar
              </button>
              <button onClick={resetForm} className="h-11 rounded-xl border border-white/25 bg-white/10 px-5 font-bold text-white">
                Limpar
              </button>
              <button
                onClick={() => fetchHistory(isCompany ? historyFilter : auth.meterId)}
                className="h-11 rounded-xl border border-white/25 bg-white/10 px-5 font-bold text-white"
              >
                Atualizar histórico
              </button>
            </div>

            <input
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              className="h-11 max-w-[360px] rounded-xl bg-white px-4 text-[14px] text-gray-900 outline-none"
            />
          </section>

          <aside className="w-[500px] rounded-xl bg-[#f2f3f5] p-7 text-gray-900">
            <div className="text-[46px] font-normal tracking-wide text-gray-600">Valor lido</div>
            <div className="mt-4 flex items-end justify-between gap-4 pb-3">
              <div className="text-[42px] font-medium tracking-wide text-gray-800">{value === null ? "—" : String(value)}</div>
              <div className="flex items-center gap-2 pb-2 text-sm text-gray-500">
                <span>{unitText}</span>
                <span className={`inline-flex h-[18px] w-[18px] items-center justify-center rounded-[4px] bg-[#f2c230] font-black text-gray-900 ${value === null ? "opacity-30" : "opacity-100"}`}>✓</span>
              </div>
            </div>

            <div className="text-sm text-gray-500">Confiança: {reading?.confidence ? `${Math.round(reading.confidence * 100)}%` : "—"}</div>
            <div className="my-4 h-px bg-gray-900/15" />

            <div className="flex items-center justify-between gap-3">
              <div className="text-[40px] font-normal tracking-wide text-gray-600">Leituras anteriores</div>
              <button onClick={() => fetchHistory(isCompany ? historyFilter : auth.meterId)} className="rounded-lg bg-[#f2c230] px-4 py-2 text-sm font-bold">
                Atualizar
              </button>
            </div>

            {isCompany && (
              <input
                value={historyFilter}
                onChange={(e) => setHistoryFilter(e.target.value)}
                placeholder="filtrar por medidor ou vazio para todos"
                className="mt-4 h-10 w-full rounded-lg border border-gray-200 px-3 outline-none"
              />
            )}

            <table className="mt-5 w-full border-collapse text-sm text-gray-700">
              <thead>
                <tr className="border-b border-gray-900/15 text-gray-500">
                  <th className="py-2 text-left font-semibold">data</th>
                  <th className="py-2 text-left font-semibold">medidor</th>
                  <th className="py-2 text-right font-semibold">valor</th>
                </tr>
              </thead>
              <tbody>
                {history.length ? (
                  history.slice(0, 8).map((item) => (
                    <tr key={item.id} className="border-b border-dashed border-gray-900/10">
                      <td className="py-3">{formatDate(item.timestamp)}</td>
                      <td className="py-3">{item.meter_id || "—"}</td>
                      <td className="py-3 text-right">{item.value ?? "—"} {item.unit || ""}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="py-3 text-gray-400">—</td>
                    <td className="py-3 text-gray-400">—</td>
                    <td className="py-3 text-right text-gray-400">—</td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className="mt-8 whitespace-pre-wrap rounded-xl bg-black/5 p-3 text-xs text-gray-500">{status}</div>
          </aside>
        </main>
      </div>
    </div>
  );
}
