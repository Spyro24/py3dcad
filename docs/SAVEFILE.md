# SAVEFILE.md - How things are geting saved

## General
Version = 1
Every Version can load files from older versions
the base for a save file is `{"documentName":"<name of the document>", "version":<Version>, "objects":[], "timeLine":[]}`
it is alweays a oneline json string to avoid using more storage space than necesary

## Saving a Sketch2d
the base for a sketch is `{"type":"sketch2d"}`, if the sketch contains points, `"points":[]` will be added to the sketch2d base
points will be saved as `[x,y]` and this will be added to points, they are geting referenced by their position index+
if objects like lines and circles get added `"shapes":[]` will be added to the sketch2d base
