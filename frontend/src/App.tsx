import { NavLink, Route, Routes } from "react-router-dom";
import ScanConfig from "./pages/ScanConfig";
import HitsList from "./pages/HitsList";
import TickerDetail from "./pages/TickerDetail";
import Candidates from "./pages/Candidates";

export default function App() {
  return (
    <div className="app">
      <h1>🍊 Grapefruit</h1>
      <div className="banner">
        <strong>Survivorship bias:</strong> EODHD's US symbol list is dominated by
        currently active, tradable tickers. Delisted, acquired, and bankrupt stocks are
        largely absent. Treat every hit as filtered through survivorship.
      </div>
      <nav>
        <NavLink to="/" end>Scan</NavLink>
        <NavLink to="/hits">Hits</NavLink>
        <NavLink to="/candidates">Candidates</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<ScanConfig />} />
        <Route path="/hits" element={<HitsList />} />
        <Route path="/candidates" element={<Candidates />} />
        <Route path="/ticker/:symbol" element={<TickerDetail />} />
      </Routes>
    </div>
  );
}
