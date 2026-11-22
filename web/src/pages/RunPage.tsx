import { useEffect, useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import Chat from "@/components/Chat"
import type { Scenario, Target, SimEvent } from "@/types"

export default function RunPage() {
  const { scenarioId } = useParams()
  const [params] = useSearchParams()
  const wantTarget = params.get("target")
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [target, setTarget] = useState<Target | null>(null)
  const [events, setEvents] = useState<SimEvent[]>([])
  const [running, setRunning] = useState(false)
  const started = useRef(false)

  useEffect(() => {
    fetch("/api/scenarios")
      .then((r) => r.json())
      .then((all: Scenario[]) => {
        const s = all.find((x) => x.id === scenarioId) || null
        setScenario(s)
        setTarget(s?.targets?.find((t) => t.id === wantTarget) || s?.targets?.[0] || null)
      })
  }, [scenarioId, wantTarget])

  async function start(targetId: string) {
    if (running || !targetId) return
    started.current = true
    setEvents([])
    setRunning(true)
    try {
      const res = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId, target_id: targetId }),
      })
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split("\n\n")
        buf = parts.pop() || ""
        for (const p of parts) {
          const line = p.split("\n").find((l) => l.startsWith("data: "))
          if (!line) continue
          const ev = JSON.parse(line.slice(6)) as SimEvent
          setEvents((prev) => [...prev, ev])
        }
      }
    } catch (e) {
      setEvents((prev) => [...prev, { kind: "error", text: String(e) }])
    } finally {
      setRunning(false)
    }
  }

  // Auto-start as soon as we know the target (the card already chose it).
  useEffect(() => {
    if (target && !started.current) start(target.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  const finished = started.current && !running

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">← Scenarios</Link>
        {finished && (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => target && start(target.id)}>Run again</Button>
            <Link to={`/history/${scenarioId}?target=${target?.id ?? ""}`} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              See history
            </Link>
          </div>
        )}
      </div>

      <h1 className="text-2xl font-semibold tracking-tight mt-3">
        {target ? target.name : scenario?.company || scenarioId}
      </h1>
      {target && <p className="text-sm text-muted-foreground">{target.role}</p>}

      <div className="mt-6">
        {events.length === 0 && !running ? (
          <p className="text-muted-foreground text-sm">Starting a live session… real recon and crafted messages. This can take a few minutes.</p>
        ) : (
          <Chat events={events} running={running} />
        )}
      </div>
    </div>
  )
}
