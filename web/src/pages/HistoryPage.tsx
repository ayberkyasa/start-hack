import { useEffect, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import Chat from "@/components/Chat"
import type { SimRecord } from "@/types"

export default function HistoryPage() {
  const { scenarioId } = useParams()
  const [params] = useSearchParams()
  const target = params.get("target")
  const [list, setList] = useState<SimRecord[]>([])
  const [selected, setSelected] = useState<SimRecord | null>(null)

  useEffect(() => {
    fetch(`/api/history/${scenarioId}`)
      .then((r) => r.json())
      .then((all: SimRecord[]) => setList(target ? all.filter((s) => s.target?.id === target) : all))
  }, [scenarioId, target])

  function open(sim_id: string) {
    fetch(`/api/history/${scenarioId}/${sim_id}`).then((r) => r.json()).then(setSelected)
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">← Scenarios</Link>
      <h1 className="text-2xl font-semibold tracking-tight mt-3 capitalize">{scenarioId} history</h1>

      <div className="mt-5 grid gap-5 md:grid-cols-[18rem_1fr]">
        <div className="flex flex-col gap-2">
          {list.length === 0 && <p className="text-sm text-muted-foreground">No simulations yet.</p>}
          {list.map((s) => (
            <button key={s.sim_id} onClick={() => open(s.sim_id)} className="text-left">
              <Card className={cn("transition-colors hover:border-ring", selected?.sim_id === s.sim_id && "border-ring ring-1 ring-ring")}>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm">{s.target?.name}</span>
                    <Badge variant={s.won?.length ? "success" : "secondary"}>
                      {s.won?.length ? s.won.join(", ") : "no win"}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {new Date(s.started_at).toLocaleString()}
                  </div>
                </CardContent>
              </Card>
            </button>
          ))}
        </div>

        <div>
          {selected ? (
            <Chat events={selected.events || []} />
          ) : (
            <p className="text-sm text-muted-foreground">Select a simulation to replay its conversation.</p>
          )}
        </div>
      </div>
    </div>
  )
}
