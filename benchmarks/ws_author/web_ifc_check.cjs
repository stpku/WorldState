/* Independent web-ifc reader and geometry check of a generated text design. */
const fs=require('fs');const WebIFC=require('web-ifc');
async function main(){const [file,report]=process.argv.slice(2);if(!file||!report||fs.existsSync(report))throw Error('usage: node web_ifc_check.cjs INPUT_IFC NEW_REPORT');
const api=new WebIFC.IfcAPI();await api.Init();const model=api.OpenModel(new Uint8Array(fs.readFileSync(file)));
const types={walls:WebIFC.IFCWALL,slabs:WebIFC.IFCSLAB,doors:WebIFC.IFCDOOR,windows:WebIFC.IFCWINDOW,openings:WebIFC.IFCOPENINGELEMENT,voids:WebIFC.IFCRELVOIDSELEMENT,fills:WebIFC.IFCRELFILLSELEMENT};
const ids={};for(const [k,v] of Object.entries(types)){const a=api.GetLineIDsWithType(model,v);ids[k]=Array.from({length:a.size()},(_,i)=>a.get(i))}
const products=[...ids.walls,...ids.slabs,...ids.doors,...ids.windows];let geometry=[];api.StreamAllMeshes(model,mesh=>{if(mesh.geometries.size())geometry.push(mesh.expressID)});
const guids={};for(const id of products)guids[id]=api.GetLine(model,id).GlobalId.value;
const result={engine:'web-ifc',counts:Object.fromEntries(Object.entries(ids).map(([k,v])=>[k,v.length])),products_with_geometry:products.filter(x=>geometry.includes(x)).length,products_total:products.length,unique_guids:new Set(Object.values(guids)).size,product_guids:Object.values(guids).sort(),schema:api.GetModelSchema(model)};
api.CloseModel(model);if(result.products_with_geometry!==result.products_total||result.unique_guids!==result.products_total||result.counts.openings!==result.counts.voids||result.counts.openings!==result.counts.fills)throw Error('web-ifc geometry, identity or relation count check failed: '+JSON.stringify(result));
fs.writeFileSync(report,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));}
main().catch(e=>{console.error(e);process.exitCode=1});
