import { Link, useLocation } from "react-router-dom";

export function TopBar() {
  const { pathname } = useLocation();
  const level = pathname.startsWith("/distribution") ? "distribution" : "transmission";
  // On a project page, neither tab is forced active.
  const onProject = pathname.startsWith("/project");

  return (
    <header className="topbar">
      <Link to="/" className="wordmark">
        <b>Grid<span className="spark">Review</span></b>
        <small>Interconnection Console</small>
      </Link>

      <nav className="levelswitch">
        <Link to="/transmission" className={!onProject && level === "transmission" ? "active" : ""}>
          <span className="dot" /> Transmission
        </Link>
        <Link to="/distribution" className={!onProject && level === "distribution" ? "active" : ""}>
          <span className="dot" /> Distribution
        </Link>
      </nav>

      <div className="spacer" />
      <div className="env">
        <span className="live" /> NESO Operator · Agent online
      </div>
    </header>
  );
}
