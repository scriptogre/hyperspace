#[macro_use]
extern crate rocket;

#[get("/")]
fn index() -> &'static str {
    "hyperspace"
}

#[launch]
fn rocket() -> _ {
    rocket::build().mount("/", routes![index])
}
