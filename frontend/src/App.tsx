import { Hammer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";
import Dashboard from "./pages/Dashboard";
import Workspace from "./pages/Workspace";

export default function App() {
  const [location, setLocation] = useState(
    `${window.location.pathname}${window.location.search}`,
  );

  useEffect(() => {
    const listener = () => {
      setLocation(`${window.location.pathname}${window.location.search}`);
      window.scrollTo({ top: 0, behavior: "auto" });
    };
    window.addEventListener("popstate", listener);
    return () => window.removeEventListener("popstate", listener);
  }, []);

  const jobId = useMemo(() => {
    const path = location.split("?")[0];
    return path.match(/^\/jobs\/([^/]+)$/)?.[1] ?? null;
  }, [location]);

  return (
    <>
      <nav className="app-nav" aria-label="แอปพลิเคชัน">
        <a className="brand" href="/" onClick={(event) => {
          event.preventDefault();
          window.history.pushState({}, "", "/");
          window.dispatchEvent(new PopStateEvent("popstate"));
        }}>
          <span className="brand-mark"><Hammer aria-hidden="true" /></span>
          <span><strong>ThaiForge</strong><small>AI Game Localization</small></span>
        </a>
        <span className="local-badge">LOCAL WORKBENCH</span>
      </nav>
      {jobId ? <Workspace jobId={jobId} /> : <Dashboard />}
      <Toaster
        position="top-right"
        richColors
        closeButton
        toastOptions={{ className: "app-toast" }}
      />
    </>
  );
}

