import { describe, expect, it } from "vitest"
import {
  appointmentBreakdown,
  appointmentCapNote,
  filterPeople,
  formatAppointments,
  formatSeats,
  leftoverMisses,
  personInvestigated,
  personInitials,
  roleSummaryParts,
} from "./researchPeople"

describe("researchPeople", () => {
  it("keeps group misses and drops person leftover", () => {
    expect(
      leftoverMisses([
        "Kvar att kartlägga: 2",
        "Fler uppdrag: Carl Jesper Thomelius har 117 bolag, tog 25",
        "Inga bolag för person: X",
        "Webbsök: Hanna Elin Fremred: Instagram: duckduckgo search failed: No results found.",
        "Allabolag hade ingen koncern för 559000-0001",
      ]),
    ).toEqual(["Allabolag hade ingen koncern för 559000-0001"])
  })

  it("finds the cap note for one person", () => {
    expect(
      appointmentCapNote(
        ["Fler uppdrag: Carl Jesper Thomelius har 117 bolag, tog 25"],
        "Carl Jesper Thomelius",
      ),
    ).toBe("Fler uppdrag: Carl Jesper Thomelius har 117 bolag, tog 25")
    expect(appointmentCapNote(["Fler uppdrag: Annan"], "Carl Jesper Thomelius")).toBeUndefined()
  })

  it("joins several roles at the same company", () => {
    expect(
      formatSeats([
        { namn: "Devbrains AB", orgnr: "559085-5473", roll: "Verkställande direktör" },
        { namn: "Devbrains AB", orgnr: "559085-5473", roll: "Ledamot" },
        { namn: "FA Consulting Group AB", orgnr: "556795-8615", roll: "Ledamot" },
      ]),
    ).toBe(
      "Devbrains AB (Verkställande direktör, Ledamot), FA Consulting Group AB (Ledamot)",
    )
  })

  it("formats appointments with orgnr", () => {
    expect(
      formatAppointments([
        { namn: "Yoga Fremred AB", orgnr: "559358-2603" },
        { namn: "Namnlös", orgnr: "" },
      ]),
    ).toBe("Yoga Fremred AB (559358-2603), Namnlös")
  })

  it("splits in-group and outside appointments", () => {
    const person = {
      namn: "Ada",
      roll: "Ledamot",
      poster: [
        { namn: "Koncern AB", orgnr: "556000-0001", roll: "Ledamot" },
        { namn: "Koncern AB", orgnr: "556000-0001", roll: "VD" },
      ],
      bolag: [
        { namn: "Koncern AB", orgnr: "556000-0001" },
        { namn: "Utomstående AB", orgnr: "556000-0002" },
      ],
      web_hits: [],
    }
    const group = new Set(["556000-0001"])
    const stats = appointmentBreakdown(person, group)
    expect(stats.inGroupCount).toBe(1)
    expect(stats.outsideCount).toBe(1)
    expect(stats.inGroup).toHaveLength(1)
    expect(stats.outside.map((row) => row.orgnr)).toEqual(["556000-0002"])
  })

  it("filters by search and investigation state", () => {
    const people = [
      {
        namn: "Ada Lovelace",
        roll: "VD",
        poster: [{ namn: "Alpha AB", orgnr: "556000-0001", roll: "VD" }],
        bolag: [{ namn: "Beta AB", orgnr: "556000-0002" }],
        web_hits: [{ title: "LinkedIn", url: "https://example.com", natverk: "LinkedIn" }],
      },
      {
        namn: "Bo Karlsson",
        roll: "Ledamot",
        poster: [{ namn: "Alpha AB", orgnr: "556000-0001", roll: "Ledamot" }],
        bolag: [],
        web_hits: [],
      },
    ]
    expect(personInvestigated(people[0])).toBe(true)
    expect(personInvestigated(people[1])).toBe(false)
    expect(filterPeople(people, "beta", "all").map((p) => p.namn)).toEqual(["Ada Lovelace"])
    expect(filterPeople(people, "", "notInvestigated").map((p) => p.namn)).toEqual(["Bo Karlsson"])
    expect(personInitials("Ada Lovelace")).toBe("AL")
    expect(roleSummaryParts(people[0])).toEqual([{ roll: "VD", count: 1 }])
  })
})
