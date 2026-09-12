import { describe, expect, it } from "vitest"

import { buildSections, isHeading1 } from "./sections"

describe("buildSections", () => {
  it("starts a section on Heading 1 and keeps H2 as a raw paragraph", () => {
    const sections = buildSections([
      { index: 0, text: "Inledning", style: "Heading 1", list_string: "1." },
      { index: 1, text: "Första stycket är tillräckligt långt.", style: "Normal", list_string: "" },
      { index: 2, text: "kort", style: "Normal", list_string: "" },
      { index: 3, text: "Detta ser ut som en underrubrik.", style: "Heading 2", list_string: "1.1." },
      { index: 4, text: "Andra stycket är också tillräckligt långt.", style: "Normal", list_string: "" },
    ])
    expect(sections).toEqual([
      {
        heading: "Inledning",
        heading_style: "Heading 1",
        heading_paragraph_index: 0,
        heading_unique_local_id: null,
        paragraphs: [
          { index: 1, text: "Första stycket är tillräckligt långt.", style: "Normal", list_string: "" },
          { index: 2, text: "kort", style: "Normal", list_string: "" },
          { index: 3, text: "Detta ser ut som en underrubrik.", style: "Heading 2", list_string: "1.1." },
          { index: 4, text: "Andra stycket är också tillräckligt långt.", style: "Normal", list_string: "" },
        ],
      },
    ])
  })

  it("opens an implicit section before the first heading", () => {
    const sections = buildSections([
      { index: 0, text: "Ingress utan rubrik.", style: "Normal", list_string: "" },
      { index: 1, text: "Nästa del", style: "Rubrik 1", list_string: "2." },
      { index: 2, text: "Brödtext efter rubrik.", style: "Normal", list_string: "" },
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
  })

  it("copies unique_local_id onto the heading and keeps it on paragraphs", () => {
    const sections = buildSections([
      {
        index: 0,
        text: "Inledning",
        style: "Heading 1",
        list_string: "",
        unique_local_id: "h-1",
      },
      {
        index: 1,
        text: "Första stycket är tillräckligt långt.",
        style: "Normal",
        list_string: "",
        unique_local_id: "p-1",
      },
    ])
    expect(sections[0]?.heading_unique_local_id).toBe("h-1")
    expect(sections[0]?.paragraphs[0]?.unique_local_id).toBe("p-1")
  })

  it("recognizes localized Heading 1 names", () => {
    expect(isHeading1("heading 1")).toBe(true)
    expect(isHeading1("Rubrik 1")).toBe(true)
    expect(isHeading1("Heading 2")).toBe(false)
  })
})
