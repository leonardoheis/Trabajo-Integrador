import { createBrowserRouter } from "react-router";
import Layout from "./components/Layout";
import RequireAuth from "./components/RequireAuth";
import RequireAdmin from "./components/RequireAdmin";
import LoginPage from "./pages/LoginPage";
import OAuthPopupPage from "./pages/OAuthPopupPage";
import ChatPage from "./pages/ChatPage";
import ProcessingPage from "./pages/ProcessingPage";
import ClassificationPage from "./pages/ClassificationPage";
import DocumentDetailPage from "./pages/DocumentDetailPage";
import UsersPage from "./pages/UsersPage";
import AuditLogPage from "./pages/AuditLogPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/oauth-popup", element: <OAuthPopupPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <ProcessingPage /> },
          { path: "/classification", element: <ClassificationPage /> },
          { path: "/documents/:jobId", element: <DocumentDetailPage /> },
          { path: "/chat", element: <ChatPage /> },
          { path: "/review", element: <ReviewQueuePage /> },
          {
            element: <RequireAdmin />,
            children: [
              { path: "/users", element: <UsersPage /> },
              { path: "/audit", element: <AuditLogPage /> },
            ],
          },
        ],
      },
    ],
  },
]);
