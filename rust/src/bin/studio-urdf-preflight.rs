//! Read-only saved-source preflight. No evaluator or export fidelity is implied.
use anyhow::{bail, ensure, Context, Result};
use serde_json::{json, Value};
use std::{collections::{BTreeMap, BTreeSet}, fs, io::Read, path::{Path, PathBuf}};
const MAX_BYTES:u64=64*1024*1024;
#[derive(Default)]
struct Scan { sources:BTreeMap<String,String>, edges:Vec<Value>, active:BTreeSet<PathBuf>, total:u64, coupling:bool }
fn resolve(root:&Path, owner:&Path, raw:&str)->Result<PathBuf>{
 let s=raw.replace('\\',"/");
 ensure!(!s.is_empty()&&!s.starts_with('/')&&!s.contains(':'),"unsafe import path: {raw}");
 let p=owner.join(s).canonicalize().context("missing source")?;
 ensure!(p.starts_with(root),"source escapes project"); Ok(p)
}
fn array<'a>(d:&'a Value,k:&str)->Result<&'a Vec<Value>> { if d.get(k).is_none(){ static EMPTY:Vec<Value>=Vec::new(); Ok(&EMPTY) }else{d[k].as_array().with_context(||format!("invalid {k}"))} }
fn id(v:&Value)->Result<u64>{v.as_u64().filter(|x|*x>0).context("invalid identity")}
impl Scan {
 fn visit(&mut self,root:&Path,p:&Path,depth:usize)->Result<Value>{
 ensure!(depth<=16,"dependency depth limit"); ensure!(!self.active.contains(p),"dependency cycle");
 let key=p.strip_prefix(root)?.to_string_lossy().replace('\\',"/");
 if self.sources.contains_key(&key){return Ok(Value::Null)}
 ensure!(self.sources.len()<256,"source count limit");
 ensure!(fs::metadata(p)?.len()<=MAX_BYTES,"compressed size limit");
 let bytes=fs::read(p)?; self.total+=bytes.len() as u64; ensure!(self.total<=256*1024*1024,"closure size limit");
 let mut z=zip::ZipArchive::new(std::io::Cursor::new(&bytes))?;
 ensure!(z.len()<=1024,"entry count limit");
 let mut names=BTreeSet::new(); let mut expanded=0;
 for i in 0..z.len(){let e=z.by_index(i)?; ensure!(names.insert(e.name()?.into_owned()),"duplicate ZIP entry"); expanded+=e.size(); ensure!(expanded<=MAX_BYTES,"expanded size limit");}
 let mut text=String::new(); z.by_name("document.json")?.take(MAX_BYTES+1).read_to_string(&mut text)?;
 let d:Value=serde_json::from_str(&text)?;
 ensure!(d["format"]=="solidcraft/34"&&d["units"]=="mm","unsupported format or units");
 let mut ids=BTreeSet::new();
 for k in ["features","components","occurrences"]{for v in array(&d,k)?{ensure!(ids.insert(id(&v["id"])?),"duplicate identity");}}
 self.active.insert(p.to_owned());
 for f in array(&d,"features")? {
  ensure!(f.get("suppressed").is_none_or(Value::is_boolean),"ambiguous suppression");
  if let Some(blob)=f.get("step_blob").and_then(Value::as_str){ensure!(names.contains(blob),"missing embedded blob");}
  if f["type"]!="import"||f["suppressed"]==true {continue}
  let raw=f["file"].as_str().context("missing import file")?;
  let child=resolve(root,p.parent().unwrap(),raw)?;
  let component=id(&f["component"])?;
  let link=&d["links"][component.to_string()];
  ensure!(link["feature"]==f["id"],"source link feature mismatch");
  ensure!(resolve(root,p.parent().unwrap(),link["path"].as_str().context("missing source link")?)?==child,"source link path mismatch");
  for o in array(&d,"occurrences")?.iter().filter(|o|o["component"]==f["component"]){self.edges.push(json!({"owner":key,"occurrence":o["id"],"feature":f["id"],"source":child.strip_prefix(root)?.to_string_lossy()}));}
  self.visit(root,&child,depth+1)?;
 }
 let components:BTreeSet<u64>=array(&d,"components")?.iter().map(|v|id(&v["id"])).collect::<Result<_>>()?;
 let mut incoming=BTreeMap::new();
 for o in array(&d,"occurrences")?{ensure!(components.contains(&id(&o["component"])?),"missing occurrence component");ensure!(o["parent"]==0,"nested occurrence unsupported");incoming.insert(id(&o["id"])?,None);}
 let mut joint_ids=BTreeSet::new();
 if let Some(joints)=d["assembly"]["joints"].as_array(){for j in joints {
  ensure!(joint_ids.insert(id(&j["id"])? )&&ids.insert(id(&j["id"])?),"duplicate joint identity");
  ensure!(matches!(j["kind"].as_str(),Some("fixed"|"revolute"|"slider")),"unsupported joint kind");
  let a=id(&j["a"]["occurrence"])?;let b=id(&j["b"]["occurrence"])?;
  ensure!(a!=b&&incoming.contains_key(&a)&&incoming.contains_key(&b),"invalid joint endpoint");
  ensure!(incoming.insert(b,Some(a)).flatten().is_none(),"multiple joint parents");
 }}
 if !incoming.is_empty(){ensure!(incoming.values().filter(|v|v.is_none()).count()==1,"ambiguous roots");for start in incoming.keys(){let mut seen=BTreeSet::new();let mut cur=Some(*start);while let Some(n)=cur{ensure!(seen.insert(n),"joint cycle");cur=incoming[&n];}}}
 self.coupling|=d["assembly"]["links"].as_array().is_some_and(|a|!a.is_empty());
 self.active.remove(p);self.sources.insert(key,blake3::hash(&bytes).to_hex().to_string()); Ok(d)
 }
}
fn run(project:&Path,assembly:&str)->Result<Value>{let root=project.canonicalize()?;let p=resolve(&root,&root,assembly)?;let mut s=Scan::default();s.visit(&root,&p,0)?;Ok(json!({"schema":"datum.studio-source-preflight/1","source_checks":"pass","source_fidelity":if s.coupling{"fail"}else{"unknown"},"issues":if s.coupling{vec!["unsupported_assembly_links"]}else{vec![]},"sources":s.sources,"occurrence_edges":s.edges,"unproven":["cached_geometry_freshness","transforms_and_joint_frames","physics_readiness"],"limits":{"depth":16,"sources":256,"archive_entries":1024,"archive_bytes":MAX_BYTES,"closure_bytes":268435456}}))}
fn main(){let a:Vec<String>=std::env::args().collect();let result=if a.len()==3{run(Path::new(&a[1]),&a[2])}else{bail_usage()};match result{Ok(v)=>{println!("{}",v);if v["source_fidelity"]=="fail"{std::process::exit(1)}},Err(e)=>{println!("{}",json!({"schema":"datum.studio-source-preflight/1","source_checks":"fail","code":"invalid_source","evidence":format!("{e:#}")}));std::process::exit(1)}}}
fn bail_usage()->Result<Value>{bail!("usage: studio-urdf-preflight PROJECT ASSEMBLY")}
#[cfg(test)] mod tests {use super::*;#[test]fn paths(){let t=tempfile::tempdir().unwrap();fs::write(t.path().join("a"),b"x").unwrap();assert!(resolve(t.path(),t.path(),"a").is_ok());assert!(resolve(t.path(),t.path(),"/etc/passwd").is_err());assert!(resolve(t.path(),t.path(),"../missing").is_err());}#[test]fn malformed_archive(){let t=tempfile::tempdir().unwrap();fs::write(t.path().join("a.sc"),b"bad").unwrap();assert!(run(t.path(),"a.sc").is_err());}}
