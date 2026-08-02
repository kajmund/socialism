import type { ButtonHTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

type AdminButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "accent"
  size?: "sm" | "md"
  children: ReactNode
}

const variants = {
  primary:
    "border-transparent bg-db-black text-db-ink-0 hover:bg-db-ink-800",
  secondary:
    "border-[color:var(--border-hairline)] bg-db-ink-0 text-[color:var(--text-body)] hover:border-db-ink-950",
  accent:
    "border-transparent bg-db-gold-500 text-db-navy-ink hover:bg-db-gold-700",
} as const

const sizes = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2.5 text-sm",
} as const

export function AdminButton({
  variant = "primary",
  size = "md",
  className,
  children,
  ...props
}: AdminButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center justify-center rounded-[var(--radius-md)] border font-normal transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
