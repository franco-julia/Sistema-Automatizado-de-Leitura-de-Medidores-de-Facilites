import { useEffect, useMemo, useState } from "react";
import ufgLogo from "./assets/UFG_branco.png";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

const emptyAuth = {
  name: "",
  email: "",
  password: "",
  role: "user",
};

const emptyUploadForm = {
  meter_id: "",
  file: null,
};

const emptyMeterForm = {
  serial: "",
  utility: "water",
  type: "digital",
  multiplier: "1",
  user_id: "",
};

function normalizeUser(data) {
  return {
    id: data.id,
    name: data.name || data.nome || "Usuário",
    email: data.email,
    role: data.role || data.cargo || "user",
  };
}

function App() {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem("user");
    return saved ? normalizeUser(JSON.parse(saved)) : null;
  });

  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState(emptyAuth);
  const [message, setMessage] = useState("");

  const [historico, setHistorico] = useState([]);
  const [meters, setMeters] = useState([]);
  const [users, setUsers] = useState([]);
  const [summary, setSummary] = useState(null);

  const [meterFilter, setMeterFilter] = useState("");
  const [loading, setLoading] = useState(false);

  const [uploadForm, setUploadForm] = useState(emptyUploadForm);
  const [meterForm, setMeterForm] = useState(emptyMeterForm);

  async function apiFetch(path, options = {}) {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(options.headers || {}),
      },
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || data.message || "Erro na requisição");
    }

    return data;
  }

  async function carregarDados() {
    if (!user) return;

    try {
      const isUser = user.role === "user";
      const userQuery = isUser ? `?user_id=${user.id}` : "";
      const meterQuery = meterFilter ? `?meter_id=${encodeURIComponent(meterFilter)}` : "";

      const [readingsData, metersData, summaryData] = await Promise.all([
        apiFetch(`/api/readings${meterQuery}`),
        apiFetch(`/api/meters${userQuery}`),
        apiFetch(`/api/dashboard/summary${userQuery}`),
      ]);

      setHistorico(readingsData.items || []);
      setMeters(metersData.items || []);
      setSummary(summaryData);

      if (user.role === "company" || user.role === "admin") {
        const usersData = await apiFetch("/api/users?role=user");
        setUsers(usersData.items || []);
      }
    } catch (error) {
      setMessage(error.message || "Erro ao carregar dados.");
    }
  }

  useEffect(() => {
    carregarDados();
  }, [user]);

  async function handleRegister(event) {
    event.preventDefault();
    setMessage("");

    try {
      await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify(authForm),
      });

      setMessage("Cadastro realizado. Faça login para continuar.");
      setAuthMode("login");
    } catch (error) {
      setMessage(error.message || "Erro ao cadastrar.");
    }
  }

  async function handleLogin(event) {
    event.preventDefault();
    setMessage("");

    try {
      const data = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: authForm.email,
          password: authForm.password,
        }),
      });

      const loggedUser = normalizeUser(data.user);

      setUser(loggedUser);
      localStorage.setItem("user", JSON.stringify(loggedUser));
      localStorage.setItem("token", data.access_token || "");
    } catch {
      setMessage("Email ou senha inválidos.");
    }
  }

  async function handleCreateMeter(event) {
    event.preventDefault();
    setMessage("");

    try {
      const ownerId = user.role === "user" ? user.id : meterForm.user_id || null;

      await apiFetch("/api/meters", {
        method: "POST",
        body: JSON.stringify({
          serial: meterForm.serial,
          utility: meterForm.utility,
          type: meterForm.type,
          multiplier: Number(meterForm.multiplier || 1),
          user_id: ownerId,
        }),
      });

      setMeterForm(emptyMeterForm);
      setMessage("Medidor cadastrado com sucesso.");
      carregarDados();
    } catch (error) {
      setMessage(error.message || "Erro ao cadastrar medidor.");
    }
  }

  async function handleUpload(event) {
    event.preventDefault();

    if (!uploadForm.meter_id || !uploadForm.file) {
      setMessage("Informe o medidor e selecione uma imagem.");
      return;
    }

    const selectedMeter = meters.find((meter) => meter.serial === uploadForm.meter_id);

    if (!selectedMeter) {
      setMessage("Medidor não encontrado.");
      return;
    }

    setLoading(true);
    setMessage("");

    try {
      const formData = new FormData();
      formData.append("meter_id", selectedMeter.serial);
      formData.append("utility", selectedMeter.utility);
      formData.append("file", uploadForm.file);

      const uploadData = await apiFetch("/api/uploads", {
        method: "POST",
        body: formData,
      });

      await apiFetch("/api/readings", {
        method: "POST",
        body: JSON.stringify({
          job_id: uploadData.job_id,
          meter_id: selectedMeter.serial,
          utility: selectedMeter.utility,
          type: selectedMeter.type,
          value: uploadData.value,
          confidence: uploadData.confidence,
          raw_text: uploadData.raw_text,
          unit: uploadData.unit,
          model_version: uploadData.model_version,
          timestamp: uploadData.timestamp,
          image_url: uploadData.path,
        }),
      });

      setUploadForm(emptyUploadForm);
      setMessage("Leitura enviada e registrada com sucesso.");
      carregarDados();
    } catch (error) {
      setMessage(error.message || "Erro ao enviar leitura.");
    } finally {
      setLoading(false);
    }
  }

  async function limparHistorico() {
    const confirmar = window.confirm(
      "Deseja realmente apagar TODOS os históricos e TODOS os medidores cadastrados?"
    );

    if (!confirmar) return;

    try {
      await apiFetch("/api/reset", { method: "DELETE" });
      setMessage("Histórico e medidores removidos com sucesso.");
      carregarDados();
    } catch {
      setMessage("Erro ao limpar histórico e medidores.");
    }
  }

  function logout() {
    localStorage.clear();
    setUser(null);
    setHistorico([]);
    setMeters([]);
    setUsers([]);
    setSummary(null);
  }

  if (!user) {
    return (
      <main className="auth-page">
        <section className="auth-left">
          <img src={ufgLogo} alt="Logo UFG" className="ufg-logo" />
        </section>

        <section className="auth-right">
          <div className="login-box">
            <h1>Login</h1>

            <form className="auth-form" onSubmit={authMode === "login" ? handleLogin : handleRegister}>
              {authMode === "register" && (
                <input
                  placeholder="nome"
                  value={authForm.name}
                  onChange={(e) => setAuthForm({ ...authForm, name: e.target.value })}
                  required
                />
              )}

              <input
                type="email"
                placeholder="e-mail"
                value={authForm.email}
                onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                required
              />

              <input
                type="password"
                placeholder="senha"
                value={authForm.password}
                onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
                required
              />

              {authMode === "register" && (
                <select
                  value={authForm.role}
                  onChange={(e) => setAuthForm({ ...authForm, role: e.target.value })}
                >
                  <option value="user">Usuário local</option>
                  <option value="company">Concessionária</option>
                  <option value="admin">Administrador</option>
                </select>
              )}

              <button className="forgot-button" type="button">
                Recuperar Senha
              </button>

              <button className="primary-button" type="submit">
                {authMode === "login" ? "Entrar" : "Criar conta"}
              </button>

              <button
                className="switch-auth"
                type="button"
                onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              >
                {authMode === "login" ? "Criar cadastro" : "Já tenho conta"}
              </button>
            </form>

            {message && <p className="message">{message}</p>}
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard">
      <aside className="sidebar">
        <div className="sidebar-top">
          <img src={ufgLogo} alt="UFG" className="sidebar-logo" />
        </div>

        <div className="sidebar-divider"></div>

        <nav>
          <a href="#resumo">Resumo</a>
          <a href="#medidores">Medidores</a>
          <a href="#historico">Histórico</a>
          {(user.role === "company" || user.role === "admin") && <a href="#usuarios">Usuários</a>}
        </nav>
      </aside>

      <section className="content">
        <header className="top-header">
          <div className="topbar-title">
            <h1>{dashboardTitle(user.role)}</h1>
            <p>{dashboardSubtitle(user.role)}</p>
          </div>

          <div className="user-topbar">
            <div className="user-info-top">
              <strong>{user.name}</strong>
              <span>{roleLabel(user.role)}</span>
            </div>

            <button className="logout-top" onClick={logout}>
              Sair
            </button>
          </div>
        </header>

        <div className="top-actions">
          <button className="secondary-button" onClick={carregarDados}>
            Atualizar
          </button>

          <button className="secondary-button clear-button" onClick={limparHistorico}>
            Limpar histórico
          </button>
        </div>

        {message && <p className="message top-message">{message}</p>}

        <SummaryCards summary={summary} meters={meters} historico={historico} />

        <section className="grid-two">
          <CreateMeterCard
            user={user}
            users={users}
            meterForm={meterForm}
            setMeterForm={setMeterForm}
            handleCreateMeter={handleCreateMeter}
          />

          <UploadReadingCard
            meters={meters}
            uploadForm={uploadForm}
            setUploadForm={setUploadForm}
            handleUpload={handleUpload}
            loading={loading}
          />
        </section>

        <MetersCard meters={meters} />

        {(user.role === "company" || user.role === "admin") && (
          <UsersCard users={users} meters={meters} />
        )}

        <ConsumptionCard historico={historico} />

        <MiniHistoryCard
          title="Mini histórico"
          historico={summary?.mini_history || historico.slice(0, 5)}
        />

        <HistoryCard
          historico={historico}
          meterFilter={meterFilter}
          setMeterFilter={setMeterFilter}
          carregarDados={carregarDados}
        />
      </section>
    </main>
  );
}

function SummaryCards({ summary, meters, historico }) {
  const total =
    summary?.total_consumption ??
    historico.reduce((sum, item) => sum + Number(item.value || 0), 0);

  const avg = summary?.avg_confidence ?? averageConfidence(historico);

  return (
    <section className="cards-grid" id="resumo">
      <div className="mini-card">
        <strong>{summary?.total_meters ?? meters.length}</strong>
        <span>Medidores cadastrados</span>
      </div>

      <div className="mini-card">
        <strong>{summary?.total_readings ?? historico.length}</strong>
        <span>Leituras registradas</span>
      </div>

      <div className="mini-card">
        <strong>{formatNumber(total)}</strong>
        <span>Consumo geral</span>
      </div>

      <div className="mini-card">
        <strong>{Math.round(Number(avg || 0) * 100)}%</strong>
        <span>Confiança média</span>
      </div>
    </section>
  );
}

function CreateMeterCard({ user, users, meterForm, setMeterForm, handleCreateMeter }) {
  return (
    <section className="card" id="medidores">
      <h2>Cadastrar medidor</h2>

      <form className="form-grid" onSubmit={handleCreateMeter}>
        <label>Código/serial do medidor</label>
        <input
          value={meterForm.serial}
          onChange={(e) => setMeterForm({ ...meterForm, serial: e.target.value })}
          placeholder="Ex: A001"
          required
        />

        <label>Serviço</label>
        <select
          value={meterForm.utility}
          onChange={(e) => setMeterForm({ ...meterForm, utility: e.target.value })}
        >
          <option value="water">Água</option>
          <option value="gas">Gás</option>
          <option value="power">Energia</option>
        </select>

        <label>Tipo</label>
        <select
          value={meterForm.type}
          onChange={(e) => setMeterForm({ ...meterForm, type: e.target.value })}
        >
          <option value="digital">Digital</option>
          <option value="analog">Analógico</option>
        </select>

        <label>Multiplicador</label>
        <input
          type="number"
          step="0.01"
          value={meterForm.multiplier}
          onChange={(e) => setMeterForm({ ...meterForm, multiplier: e.target.value })}
        />

        {(user.role === "company" || user.role === "admin") && (
          <>
            <label>Vincular a usuário</label>
            <select
              value={meterForm.user_id}
              onChange={(e) => setMeterForm({ ...meterForm, user_id: e.target.value })}
            >
              <option value="">Sem vínculo</option>
              {users.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} — {item.email}
                </option>
              ))}
            </select>
          </>
        )}

        <button className="primary-button">Cadastrar medidor</button>
      </form>
    </section>
  );
}

function UploadReadingCard({ meters, uploadForm, setUploadForm, handleUpload, loading }) {
  return (
    <section className="card">
      <h2>Enviar leitura</h2>

      <form className="form-grid" onSubmit={handleUpload}>
        <label>Medidor</label>
        <select
          value={uploadForm.meter_id}
          onChange={(e) => setUploadForm({ ...uploadForm, meter_id: e.target.value })}
          required
        >
          <option value="">Selecione</option>
          {meters.map((meter) => (
            <option key={meter.id} value={meter.serial}>
              {meter.serial} — {utilityLabel(meter.utility)}
            </option>
          ))}
        </select>

        <label>Imagem</label>
        <input
          type="file"
          accept="image/*"
          onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files[0] })}
          required
        />

        <button className="primary-button" disabled={loading}>
          {loading ? "Enviando..." : "Enviar leitura"}
        </button>
      </form>
    </section>
  );
}

function MetersCard({ meters }) {
  return (
    <section className="card">
      <h2>Medidores cadastrados</h2>

      {meters.length === 0 ? (
        <p>Nenhum medidor cadastrado.</p>
      ) : (
        <div className="meter-list">
          {meters.map((meter) => (
            <article className="meter-item" key={meter.id}>
              <strong>{meter.serial}</strong>
              <span>
                {utilityLabel(meter.utility)} • {meter.type === "digital" ? "Digital" : "Analógico"}
              </span>
              <small>Multiplicador: {meter.multiplier}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function UsersCard({ users, meters }) {
  return (
    <section className="card" id="usuarios">
      <h2>Usuários da concessionária</h2>

      {users.length === 0 ? (
        <p>Nenhum usuário local cadastrado.</p>
      ) : (
        <div className="user-list">
          {users.map((user) => {
            const userMeters = meters.filter((meter) => meter.user_id === user.id);

            return (
              <article className="user-item" key={user.id}>
                <div>
                  <strong>{user.name}</strong>
                  <span>{user.email}</span>
                </div>
                <em>{userMeters.length} medidor(es)</em>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ConsumptionCard({ historico }) {
  const byMeter = useMemo(() => {
    const map = new Map();

    historico.forEach((item) => {
      const key = item.meter_id || "sem medidor";
      map.set(key, (map.get(key) || 0) + Number(item.value || 0));
    });

    return Array.from(map.entries()).map(([meter, total]) => ({ meter, total }));
  }, [historico]);

  return (
    <section className="card">
      <h2>Consumo geral por medidor</h2>

      {byMeter.length === 0 ? (
        <p>Sem dados de consumo.</p>
      ) : (
        <div className="consumption-list">
          {byMeter.map((item) => (
            <div className="consumption-row" key={item.meter}>
              <span>{item.meter}</span>
              <strong>{formatNumber(item.total)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MiniHistoryCard({ title, historico }) {
  return (
    <section className="card">
      <h2>{title}</h2>

      {historico.length === 0 ? (
        <p>Nenhuma leitura recente.</p>
      ) : (
        <div className="mini-history">
          {historico.map((item) => (
            <article key={item.id}>
              <strong>{item.meter_id}</strong>
              <span>
                {item.value} {item.unit}
              </span>
              <small>
                {item.timestamp ? new Date(item.timestamp).toLocaleString("pt-BR") : "-"}
              </small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function HistoryCard({ historico, meterFilter, setMeterFilter, carregarDados }) {
  return (
    <section className="card" id="historico">
      <div className="section-header">
        <h2>Histórico completo</h2>

        <div className="filter-row">
          <input
            value={meterFilter}
            onChange={(e) => setMeterFilter(e.target.value)}
            placeholder="Filtrar por medidor"
          />
          <button className="secondary-button" onClick={carregarDados}>
            Buscar
          </button>
        </div>
      </div>

      {historico.length === 0 ? (
        <p>Nenhuma leitura encontrada.</p>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Medidor</th>
                <th>Valor</th>
                <th>Unidade</th>
                <th>Confiança</th>
                <th>Data</th>
                <th>Status</th>
              </tr>
            </thead>

            <tbody>
              {historico.map((item) => (
                <tr key={item.id}>
                  <td>{item.meter_id}</td>
                  <td>{item.value}</td>
                  <td>{item.unit}</td>
                  <td>{item.confidence != null ? `${Math.round(item.confidence * 100)}%` : "-"}</td>
                  <td>{item.timestamp ? new Date(item.timestamp).toLocaleString("pt-BR") : "-"}</td>
                  <td>{item.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function roleLabel(role) {
  if (role === "user") return "Usuário local";
  if (role === "company") return "Concessionária";
  if (role === "admin") return "Administrador";
  return role;
}

function dashboardTitle(role) {
  if (role === "user") return "Painel do usuário";
  if (role === "company") return "Dashboard da concessionária";
  if (role === "admin") return "Painel administrativo";
  return "Dashboard";
}

function dashboardSubtitle(role) {
  if (role === "user") return "Cadastre seus medidores, envie leituras e acompanhe seu histórico.";
  if (role === "company") return "Gerencie usuários, medidores, consumo geral e histórico de leituras.";
  if (role === "admin") return "Acompanhe a operação completa da plataforma.";
  return "";
}

function utilityLabel(utility) {
  if (utility === "water") return "Água";
  if (utility === "gas") return "Gás";
  if (utility === "power") return "Energia";
  return utility;
}

function averageConfidence(items) {
  if (!items.length) return 0;

  return items.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / items.length;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("pt-BR", {
    maximumFractionDigits: 2,
  });
}

export default App;