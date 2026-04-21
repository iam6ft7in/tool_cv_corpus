// Default Typst template for tool_cv_corpus.
//
// Kept deliberately plain: one column, no boxes, simple rule separators.
// Users who want a branded template should copy this file, edit freely,
// and point the typst renderer at their copy via --template.

#set page(margin: (x: 1.75cm, y: 1.5cm))
#set text(font: "Liberation Sans", size: 10pt)
#set par(justify: false, leading: 0.55em)
#show heading.where(level: 1): set text(size: 18pt, weight: "bold")
#show heading.where(level: 2): set text(size: 12pt, weight: "bold")
#show heading.where(level: 2): it => [
  #v(0.3em)
  #it
  #line(length: 100%, stroke: 0.4pt)
  #v(0.1em)
]

#let resume(data) = {
  // Header
  heading(level: 1, data.person.full_name)
  if data.headline != none { text(style: "italic", data.headline) }
  if data.person.location != none { parbreak(); text(size: 9pt, data.person.location) }
  if data.summary != none { parbreak(); data.summary }

  // Experience
  if data.roles.len() > 0 {
    heading(level: 2, "Experience")
    for role in data.roles {
      strong(role.title)
      [, ]
      emph(role.organization_id)
      [ #h(1fr) ]
      text(size: 9pt, [#role.period.start #sym.dash #if role.period.end != none { role.period.end } else { "present" }])
      parbreak()
      if role.headline != none { text(role.headline); parbreak() }
      let role_aches = data.achievements.filter(a => a.role_id == role.id)
      if role_aches.len() > 0 {
        list(..role_aches.map(a => a.headline))
      }
      v(0.4em)
    }
  }

  // Skills
  if data.skills.len() > 0 {
    heading(level: 2, "Skills")
    list(..data.skills.map(s => [#s.name #text(size: 8pt, gray, [(#s.tier, #s.confidence)])]))
  }

  // Education
  if data.education.len() > 0 {
    heading(level: 2, "Education")
    for edu in data.education {
      strong(edu.credential)
      if edu.field_of_study != none [ in #edu.field_of_study ]
      [, #emph(edu.institution)]
      if edu.period != none [ #h(1fr) #text(size: 9pt, [#edu.period.start #sym.dash #if edu.period.end != none { edu.period.end } else { "present" }]) ]
      parbreak()
    }
  }
}

#let data = json("resume.json")
#resume(data)
