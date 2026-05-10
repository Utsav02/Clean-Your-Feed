import { useState, useEffect } from 'react'
import { API_BASE } from '../config.js'

export default function BudgetBar() {
  const [budget, setBudget] = useState(null)

  useEffect(() => {
    fetchBudget()
    const id = setInterval(fetchBudget, 30_000)
    return () => clearInterval(id)
  }, [])

  async function fetchBudget() {
    try {
      const res = await fetch(`${API_BASE}/health`)
      if (!res.ok) return
      const data = await res.json()
      if (data.budget) setBudget(data.budget)
    } catch {}
  }

  const pct  = budget?.pct ?? 0
  const over = pct > 80

  return (
    <div className="budget-bar">
      <div className="budget-bar-inner">
        <span className="budget-bar-text">
          API calls this month:&nbsp;
          <strong>{budget ? budget.used.toLocaleString() : '…'}</strong>
          {budget && <>&nbsp;/&nbsp;{budget.total.toLocaleString()}&nbsp;({pct}%)</>}
        </span>
        <div className="budget-progress-track">
          <div
            className={`budget-progress-fill${over ? ' over-80' : ''}`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
      </div>
    </div>
  )
}
