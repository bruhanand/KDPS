import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { ModulePage } from "./pages/ModulePage";
import { BrandsPage, GstinsPage, SeasonsPage, StoresPage } from "./pages/MasterPages";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Home />} />
            <Route path="/masters/stores" element={<StoresPage />} />
            <Route path="/masters/brands" element={<BrandsPage />} />
            <Route path="/masters/seasons" element={<SeasonsPage />} />
            <Route path="/masters/gstins" element={<GstinsPage />} />
            <Route path="*" element={<ModulePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
