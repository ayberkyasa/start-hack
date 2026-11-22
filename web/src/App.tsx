import { BrowserRouter, Route, Routes } from "react-router-dom"
import MainPage from "@/pages/MainPage"
import RunPage from "@/pages/RunPage"
import HistoryPage from "@/pages/HistoryPage"
import ThemeToggle from "@/components/ThemeToggle"

export default function App() {
  return (
    <BrowserRouter>
      <ThemeToggle />
      <Routes>
        <Route path="/" element={<MainPage />} />
        <Route path="/run/:scenarioId" element={<RunPage />} />
        <Route path="/history/:scenarioId" element={<HistoryPage />} />
      </Routes>
    </BrowserRouter>
  )
}
