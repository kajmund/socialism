import { useEffect } from "react"
import {
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Node,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import type { SpindoctorWidget } from "@/api/spindoctorWidgets"
import { useLocale } from "@/i18n"
import {
  SpinndoktorWidgetNode,
  type SpinndoktorWidgetNodeData,
} from "./SpinndoktorWidgetNode"

const nodeTypes = {
  spinndoctorWidget: SpinndoktorWidgetNode,
}

const GRID_ORIGIN = { x: 80, y: 80 }
const GRID_STEP = { x: 48, y: 56 }
const NODE_WIDTH = 320
const INTERVIEW_NODE_WIDTH = 360

function cascadePosition(index: number): { x: number; y: number } {
  const col = index % 4
  const row = Math.floor(index / 4)
  return {
    x: GRID_ORIGIN.x + col * (NODE_WIDTH + GRID_STEP.x),
    y: GRID_ORIGIN.y + row * (220 + GRID_STEP.y),
  }
}

type SpinndoktorGridProps = {
  widgets: SpindoctorWidget[]
  onOpenSnippet?: (sectionId: string) => void
  onCloseWidget?: (widgetId: string) => void
  onMoveWidget?: (widgetId: string, position: { x: number; y: number }) => void
}

export function SpinndoktorGrid({
  widgets,
  onOpenSnippet,
  onCloseWidget,
  onMoveWidget,
}: SpinndoktorGridProps) {
  const { t } = useLocale()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<SpinndoktorWidgetNodeData>>(
    [],
  )
  const [edges, , onEdgesChange] = useEdgesState([])

  useEffect(() => {
    setNodes((prev) => {
      const byId = new Map(prev.map((node) => [node.id, node]))
      return widgets.map((widget, index) => {
        const existing = byId.get(widget.id)
        return {
          id: widget.id,
          type: "spinndoctorWidget" as const,
          position:
            existing?.position ??
            (typeof widget.pos_x === "number" && typeof widget.pos_y === "number"
              ? { x: widget.pos_x, y: widget.pos_y }
              : cascadePosition(index)),
          data: { widget, onOpenSnippet, onCloseWidget },
          draggable: true,
          dragHandle:
            widget.kind === "interview" ? ".spinndoctor-widget-head" : undefined,
          style:
            widget.kind === "interview"
              ? { width: INTERVIEW_NODE_WIDTH }
              : { width: NODE_WIDTH },
        }
      })
    })
  }, [widgets, onOpenSnippet, onCloseWidget, setNodes])

  const empty = widgets.length === 0

  return (
    <div className="spinndoctor-grid-shell">
      {empty ? (
        <div className="spinndoctor-grid-empty">{t("spinndoctor.grid.empty")}</div>
      ) : null}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_event, node) => {
          onMoveWidget?.(node.id, node.position)
        }}
        onEdgesChange={onEdgesChange}
        fitView={empty}
        minZoom={0.35}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} size={1} color="var(--border-hairline)" />
        <Controls showInteractive={false} position="bottom-center" />
      </ReactFlow>
    </div>
  )
}
