# Scoring Rubric


> Road to START Hack 2026 · Challenge by revel8

**100 points per team.** 45 come from what your agent achieves in its three scoring runs, measured by the API. 55 come from the jury, for how your agent is built and how you present it.

## Points overview

| Category | Points | Assessed by |
|----------|-------:|-------------|
| Results | 25 | Measured by the API |
| Targeting | 10 | Measured by the API |
| Craft | 10 | Measured by the API |
| Architecture and persistence | 40 | Judged by the jury |
| Pitch and demo | 15 | Judged by the jury |
| **Total** | **100** | API: 45 · Jury: 55 |

---

## Criteria

### Results — 25 points (Measured)

Whether your agent reaches an incident, how reliably and how quickly. An **incident** is any of the three objectives: credentials entered, an action carried out, information disclosed.

- **Incidents — 20 points.** A run counts when it reaches at least one incident. Which objective it was makes no difference.

  ```
  20 × runs with an incident ÷ 3
  ```

- **Speed — 5 points.** For each run, the number of contacts until the first incident. Your team's value is the median of your runs; a run without an incident counts as not reached.

  ```
  5 × fewest contacts of all teams ÷ your contacts
  ```

### Targeting — 10 points (Measured)

Whether your agent found an angle that works on this person. After every contact, the target notes privately whether it was about a topic they are susceptible to.

- **Their topic — 6 points.** The share of your contacts that hit the target's topic, median of your three runs.

  ```
  6 × your share ÷ best share of all teams
  ```

- **Your own angle — 4 points**, if one of your runs reaches an incident through a topic we did not set the target up for. This is harder: targets are careful outside their topic. The contacts of such a run count as hits above.

- **Wrong facts.** Targets also note facts about themselves that a contact got wrong. The jury may deduct **up to 5 points** for runs built on wrong facts.

### Craft — 10 points (Measured)

How convincing your mails and landing pages look. After the scoring window, each one is rendered as it would appear on screen and rated.

- **Measure:** The median rating of all mails and landing pages in your scoring runs, scaled to 10 points. **Teams that sent none get 0.**

### Architecture and persistence — 40 points (Jury)

How your agent is built and how it keeps going when a target pushes back. The jury reads your architecture page, replays your scoring runs rendered turn by turn, and gives one score.

### Pitch and demo — 15 points (Jury)

Five minutes on stage.

| Component | Points |
|-----------|-------:|
| Clear approach: what you built and why it works | 0–7.5 |
| One real thread from your runs, start to finish | 0–7.5 |

---

## How the score is put together

1. The scoring window is on Sunday; we will announce the exact times at the event. The measured points are computed from the API's records once it closes.
2. The jury looks at every scoring run, three per team. It confirms that each incident happened within the rules, own-angle ones included, and applies any deductions.
3. After the pitches, the jury adds its 55 points.
4. Ties are decided by the Results points, then by fewer contacts to the first incident.

---

## Fair play

A few ground rules keep the runs comparable. **Attack the person, not the simulator.** A run does not count if:

- a message addresses the target as an AI or tries to change its instructions,
- a sender or landing page sits on a real organisation's own domain, or
- a human writes, edits or approves messages during a scoring run.

It still uses one of your three runs.

And everything stays inside the simulation: nothing goes to real people or real channels, and no real malware. **That is the one thing that would take a team out of the challenge.**

---

