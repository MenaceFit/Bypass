import { Route, Routes } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Searches } from "./pages/Searches";
import { Listings } from "./pages/Listings";
import { Statistics } from "./pages/Statistics";
import { Logs } from "./pages/Logs";
import { SettingsPage } from "./pages/Settings";

export default function App() {
  return (
    <AppProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="searches" element={<Searches />} />
          <Route path="listings" element={<Listings />} />
          <Route path="statistics" element={<Statistics />} />
          <Route path="logs" element={<Logs />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </AppProvider>
  );
}
