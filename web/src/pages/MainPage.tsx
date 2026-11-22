import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { buttonVariants } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import type { Scenario, Target } from "@/types"

type Counts = Record<string, Record<string, number>>

export default function MainPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [counts, setCounts] = useState<Counts>({})
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetch("/api/scenarios").then((r) => r.json()),
      fetch("/api/history").then((r) => r.json()),
    ])
      .then(([s, c]) => { setScenarios(s); setCounts(c) })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const kinds = Array.from(new Set(scenarios.map((s) => s.kind)))

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Phishing Simulations</h1>
      <p className="text-muted-foreground text-sm mt-1">Pick a target and run the agent against them.</p>

      {loading && <p className="mt-8 text-muted-foreground">Loading scenarios…</p>}
      {err && <p className="mt-8 text-destructive">Failed to load: {err}</p>}

      {!loading && !err && (
        <Tabs defaultValue={kinds[0]} className="mt-6">
          <TabsList>
            {kinds.map((k) => (
              <TabsTrigger key={k} value={k} className="capitalize">{k}</TabsTrigger>
            ))}
          </TabsList>

          {kinds.map((k) => (
            <TabsContent key={k} value={k} className="flex flex-col gap-6">
              {scenarios.filter((s) => s.kind === k).map((s) => (
                <ScenarioSection key={s.id} s={s} counts={counts[s.id] || {}} />
              ))}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}

function ScenarioSection({ s, counts }: { s: Scenario; counts: Record<string, number> }) {
  const targets = s.targets ?? []
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{s.company || s.id}</span>
        <Badge variant="secondary" className="capitalize">{s.kind}</Badge>
        {s.objectives?.map((o) => <Badge key={o.id} variant="outline">{o.id}</Badge>)}
      </div>

      {targets.length === 0 ? (
        <Card><CardContent className="p-5 text-sm text-muted-foreground">
          Not open yet{s.opens_at ? ` · opens ${s.opens_at}` : ""}.
        </CardContent></Card>
      ) : (
        targets.map((t) => (
          <TargetCard key={t.id} scenarioId={s.id} target={t} history={counts[t.id] || 0} />
        ))
      )}
    </section>
  )
}

function TargetCard({ scenarioId, target, history }: { scenarioId: string; target: Target; history: number }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="font-medium">{target.name}</div>
          <p className="text-sm text-muted-foreground mt-0.5">{target.role}</p>
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <Link to={`/run/${scenarioId}?target=${target.id}`} className={cn(buttonVariants(), "w-full")}>
            Run Simulation
          </Link>
          {history > 0 && (
            <Link to={`/history/${scenarioId}?target=${target.id}`} className={cn(buttonVariants({ variant: "outline" }), "w-full")}>
              See history ({history})
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
