import { Navigate, Route, Routes } from "react-router-dom";
import { AgentConsole } from "./components/AgentConsole";
import { TopBar } from "./components/TopBar";
import { Dashboard } from "./pages/Dashboard";
import { IntakePage } from "./pages/IntakePage";
import { ProjectPage } from "./pages/ProjectPage";

export default function App() {
  return (
    <>
      <TopBar />
      <Routes>
        <Route path="/" element={<Navigate to="/transmission" replace />} />
        <Route path="/transmission" element={<Dashboard />} />
        <Route path="/distribution" element={<Dashboard />} />
        <Route path="/project/:id" element={<ProjectPage />} />
        <Route path="/intake/:id" element={<IntakePage />} />
        <Route path="*" element={<Navigate to="/transmission" replace />} />
      </Routes>
      <AgentConsole />
    </>
  );
}
