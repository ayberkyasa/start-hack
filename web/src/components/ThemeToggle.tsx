import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"

function initial(): "light" | "dark" {
  try {
    const s = localStorage.getItem("theme")
    if (s === "dark" || s === "light") return s
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  } catch {
    return "light"
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(initial)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    try { localStorage.setItem("theme", theme) } catch { /* ignore */ }
  }, [theme])

  return (
    <Button
      variant="outline"
      size="icon"
      aria-label="Toggle theme"
      className="fixed top-4 right-4 z-50"
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
    >
      {theme === "dark" ? <Sun /> : <Moon />}
    </Button>
  )
}
