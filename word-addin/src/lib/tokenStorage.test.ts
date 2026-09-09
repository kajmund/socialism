import { afterEach, describe, expect, it } from "vitest"

import { clearStoredToken, getStoredToken, saveStoredToken } from "./tokenStorage"

const TOKEN_KEY = "socialism_access_token"

const memory = new Map<string, string>()

const stubStorage: Storage = {
  get length() {
    return memory.size
  },
  clear() {
    memory.clear()
  },
  getItem(key) {
    return memory.get(key) ?? null
  },
  key() {
    return null
  },
  removeItem(key) {
    memory.delete(key)
  },
  setItem(key, value) {
    memory.set(key, value)
  },
}

afterEach(() => {
  memory.clear()
  Reflect.deleteProperty(globalThis, "localStorage")
})

describe("tokenStorage", () => {
  it("returns empty when localStorage is missing", () => {
    expect(getStoredToken()).toBe("")
  })

  it("round-trips a token", () => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: stubStorage,
    })
    saveStoredToken("jwt-token")
    expect(getStoredToken()).toBe("jwt-token")
    expect(memory.get(TOKEN_KEY)).toBe("jwt-token")
    clearStoredToken()
    expect(getStoredToken()).toBe("")
  })
})
