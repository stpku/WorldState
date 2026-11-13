/* Independent web-ifc round trip for a one-wall, one-solid IFC draft.
 * This directly edits the extruded height. It deliberately does not update the
 * WorldState IR: the resulting IFC must be reviewed as an external edit. */
const fs = require("fs");
const WebIFC = require("web-ifc");

async function main() {
  const [input, output, heightText, reportPath] = process.argv.slice(2);
  const height = Number(heightText);
  if (!input || !output || !reportPath || !Number.isFinite(height) || height <= 0 || fs.existsSync(output)) {
    throw new Error("usage: node web_ifc_edit.cjs INPUT OUTPUT POSITIVE_HEIGHT REPORT; OUTPUT must not exist");
  }
  const api = new WebIFC.IfcAPI();
  await api.Init();
  const model = api.OpenModel(new Uint8Array(fs.readFileSync(input)));
  const walls = api.GetLineIDsWithType(model, WebIFC.IFCWALL);
  const solids = api.GetLineIDsWithType(model, WebIFC.IFCEXTRUDEDAREASOLID);
  if (walls.size() !== 1 || solids.size() !== 1) throw new Error("requires exactly one wall and one extruded solid");
  const wall = api.GetLine(model, walls.get(0));
  const solid = api.GetLine(model, solids.get(0));
  const before = solid.Depth.value;
  const guid = wall.GlobalId.value;
  solid.Depth.value = height;
  api.WriteLine(model, solid);
  fs.writeFileSync(output, api.SaveModel(model));
  api.CloseModel(model);
  const reopened = api.OpenModel(new Uint8Array(fs.readFileSync(output)));
  const savedWall = api.GetLine(reopened, api.GetLineIDsWithType(reopened, WebIFC.IFCWALL).get(0));
  const savedSolid = api.GetLine(reopened, api.GetLineIDsWithType(reopened, WebIFC.IFCEXTRUDEDAREASOLID).get(0));
  const report = {engine: "web-ifc 0.0.77", wall_guid_before: guid, wall_guid_after: savedWall.GlobalId.value,
                  height_before_m: before, height_after_m: savedSolid.Depth.value,
                  warning: "External IFC edit is not reflected in WorldState IR; revalidation required."};
  api.CloseModel(reopened);
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", {flag: "wx"});
  console.log(JSON.stringify(report, null, 2));
}
main().catch(error => { console.error(error); process.exit(1); });
