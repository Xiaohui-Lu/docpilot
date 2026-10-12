import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import { LoginPage } from "./pages/Login";

// Route-level code splitting keeps the initial bundle small (charts load only on the dashboard).
const DashboardPage = lazy(() => import("./pages/Dashboard").then((m) => ({ default: m.DashboardPage })));
const DocumentsPage = lazy(() => import("./pages/Documents").then((m) => ({ default: m.DocumentsPage })));
const DocumentDetailPage = lazy(() =>
  import("./pages/DocumentDetail").then((m) => ({ default: m.DocumentDetailPage })),
);
const DeadlinesPage = lazy(() => import("./pages/Deadlines").then((m) => ({ default: m.DeadlinesPage })));
const RulebookPage = lazy(() => import("./pages/Rulebook").then((m) => ({ default: m.RulebookPage })));
const AskPage = lazy(() => import("./pages/Ask").then((m) => ({ default: m.AskPage })));
const TeamPage = lazy(() => import("./pages/Team").then((m) => ({ default: m.TeamPage })));

function RequireAuth({ children, role }: { children: ReactNode; role?: Role }) {
  const { user, loading, can } = useAuth();
  if (loading) return <Spinner label="Signing in" />;
  if (!user) return <Navigate to="/login" replace />;
  if (role && !can(role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="documents/:id" element={<DocumentDetailPage />} />
          <Route path="deadlines" element={<DeadlinesPage />} />
          <Route path="rules" element={<RulebookPage />} />
          <Route path="ask" element={<AskPage />} />
          <Route
            path="team"
            element={
              <RequireAuth role="admin">
                <TeamPage />
              </RequireAuth>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
