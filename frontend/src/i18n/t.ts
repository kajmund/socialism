import type { Locale } from "./locales"
import { en } from "./messages/en"
import { sv, type SvMessages } from "./messages/sv"

type Primitive = string

/** Dot-path keys into the Swedish message tree (source of truth). */
export type MessageKey = {
  [K1 in keyof SvMessages & string]: SvMessages[K1] extends Primitive
    ? K1
    : {
        [K2 in keyof SvMessages[K1] & string]: SvMessages[K1][K2] extends Primitive
          ? `${K1}.${K2}`
          : {
              [K3 in keyof SvMessages[K1][K2] & string]: SvMessages[K1][K2][K3] extends Primitive
                ? `${K1}.${K2}.${K3}`
                : {
                    [K4 in keyof SvMessages[K1][K2][K3] & string]: SvMessages[K1][K2][K3][K4] extends Primitive
                      ? `${K1}.${K2}.${K3}.${K4}`
                      : {
                          [K5 in keyof SvMessages[K1][K2][K3][K4] & string]: SvMessages[K1][K2][K3][K4][K5] extends Primitive
                            ? `${K1}.${K2}.${K3}.${K4}.${K5}`
                            : never
                        }[keyof SvMessages[K1][K2][K3][K4] & string]
                  }[keyof SvMessages[K1][K2][K3] & string]
            }[keyof SvMessages[K1][K2] & string]
      }[keyof SvMessages[K1] & string]
}[keyof SvMessages & string]

const catalogs: Record<Locale, object> = { sv, en }

function lookup(tree: object, key: string): string | undefined {
  const parts = key.split(".")
  let node: unknown = tree
  for (const part of parts) {
    if (node == null || typeof node !== "object") return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === "string" ? node : undefined
}

export type TranslateParams = Record<string, string | number>

export function translate(
  locale: Locale,
  key: MessageKey,
  params?: TranslateParams,
): string {
  const raw = lookup(catalogs[locale], key) ?? lookup(sv, key) ?? key
  if (!params) return raw
  return raw.replace(/\{(\w+)\}/g, (_, name: string) =>
    params[name] != null ? String(params[name]) : `{${name}}`,
  )
}

export function createTranslator(locale: Locale) {
  return (key: MessageKey, params?: TranslateParams) => translate(locale, key, params)
}
