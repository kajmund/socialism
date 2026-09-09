import { describe, expect, it } from "vitest"

import { buildSections, isHeading1 } from "./sections"

describe("buildSections", () => {
  it("starts a section on Heading 1 and keeps H2 as a raw paragraph", () => {
    const sections = buildSections([
      { index: 0, text: "Inledning", style: "Heading 1" },
      { index: 1, text: "Första stycket är tillräckligt långt.", style: "Normal" },
      { index: 2, text: "kort", style: "Normal" },
      { index: 3, text: "Detta ser ut som en underrubrik.", style: "Heading 2" },
      { index: 4, text: "Andra stycket är också tillräckligt långt.", style: "Normal" },
    ])
    expect(sections).toEqual([
      {
        heading: "Inledning",
        heading_style: "Heading 1",
        heading_paragraph_index: 0,
        paragraphs: [
          { index: 0, text: "Inledning", style: "Heading 1" },
          { index: 1, text: "Första stycket är tillräckligt långt.", style: "Normal" },
          { index: 2, text: "kort", style: "Normal" },
          { index: 3, text: "Detta ser ut som en underrubrik.", style: "Heading 2" },
          { index: 4, text: "Andra stycket är också tillräckligt långt.", style: "Normal" },
        ],
      },
    ])
  })

  it("opens an implicit section before the first heading", () => {
    const sections = buildSections([
      { index: 0, text: "Ingress utan rubrik.", style: "Normal" },
      { index: 1, text: "Nästa del", style: "Rubrik 1" },
      { index: 2, text: "Brödtext efter rubrik.", style: "Normal" },
    ])
    expect(sections).toHaveLength(2)
    expect(sections[0]).toMatchObject({
      heading: "",
      heading_paragraph_index: 0,
    })
    expect(sections[1]).toMatchObject({
      heading: "Nästa del",
      heading_style: "Rubrik 1",
      heading_paragraph_index: 1,
    })
    expect(sections[1].paragraphs[0]).toMatchObject({
      index: 1,
      text: "Nästa del",
      style: "Rubrik 1",
    })
  })

  it("recognizes localized Heading 1 names", () => {
    expect(isHeading1("heading 1")).toBe(true)
    expect(isHeading1("Rubrik 1")).toBe(true)
    expect(isHeading1("Heading 2")).toBe(false)
  })
})
