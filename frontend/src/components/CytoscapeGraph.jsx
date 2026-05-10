import { useEffect, useRef } from 'react'

const ROLE_COLOR = {
  ORIGIN:    '#C0392B',
  AMPLIFIER: '#E67E22',
  SUSPECTED: '#95A5A6',
}

export default function CytoscapeGraph({ members, tweetMatches, onSelectAccount, selectedAccountId }) {
  const containerRef = useRef(null)
  const cyRef        = useRef(null)

  // Build or rebuild the graph whenever members change
  useEffect(() => {
    if (!containerRef.current || !members?.length) return
    if (!window.cytoscape) {
      console.warn('Cytoscape.js not loaded from CDN yet')
      return
    }

    const nodes = members.map((m) => ({
      data: {
        id:    m.account_id,
        label: `@${m.handle}`.slice(0, 13),
        role:  m.role,
        size:  Math.max(20, Math.min(60, 20 + (m.match_count || 1) * 8)),
      },
    }))

    // Spoke pattern: every account with a qualifying match connects to the origin.
    const originId = members.find((m) => m.role === 'ORIGIN')?.account_id
    const memberIds = new Set(members.map((m) => m.account_id))
    // Include all flagged matches (FUZZY + SEMANTIC) — if something was
    // classified as a coordination match of any type, it earns an edge.
    const accountsWithMatches = new Set(
      (tweetMatches ?? [])
        .filter((m) => m.match_type !== 'EXACT')
        .map((m) => m.account_id)
    )

    const edges = []
    if (originId) {
      accountsWithMatches.forEach((accountId) => {
        if (accountId !== originId && memberIds.has(accountId)) {
          edges.push({
            data: {
              id:     `${originId}-${accountId}`,
              source: originId,
              target: accountId,
            },
          })
        }
      })
    }

    if (cyRef.current) {
      cyRef.current.destroy()
      cyRef.current = null
    }

    const cy = window.cytoscape({
      container: containerRef.current,
      elements:  [...nodes, ...edges],
      style: [
        {
          selector: 'node',
          style: {
            width:              'data(size)',
            height:             'data(size)',
            'background-color': (ele) => ROLE_COLOR[ele.data('role')] ?? '#95A5A6',
            label:              'data(label)',
            'font-size':        '10px',
            'font-family':      'system-ui, -apple-system, sans-serif',
            color:              '#1A1A1A',
            'text-valign':      'bottom',
            'text-margin-y':    '5px',
            'border-width':     '0px',
            'border-color':     '#1A1A1A',
          },
        },
        {
          selector: 'node.highlighted',
          style: {
            'border-width': '3px',
            'border-color': '#1A1A1A',
          },
        },
        {
          selector: 'edge',
          style: {
            width:          1,
            'line-color':   '#E5E5E0',
            'curve-style':  'bezier',
          },
        },
      ],
      layout: {
        name:      'cose',
        padding:   24,
        randomize: true,
        animate:   false,
      },
    })

    cy.on('tap', 'node', (evt) => {
      onSelectAccount(evt.target.id())
    })

    cyRef.current = cy

    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [members, onSelectAccount])

  // Update highlighted node without rebuilding the graph
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().removeClass('highlighted')
    if (selectedAccountId) {
      cy.$(`#${CSS.escape(selectedAccountId)}`).addClass('highlighted')
    }
  }, [selectedAccountId])

  return <div ref={containerRef} className="cytoscape-container" />
}
