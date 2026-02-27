/// Generate a random u64 using the standard library's random hasher seed.
pub fn random_u64() -> u64 {
    use std::hash::{BuildHasher, Hasher};
    std::collections::hash_map::RandomState::new().build_hasher().finish()
}

pub fn random_color() -> String {
    const PALETTE: [&str; 8] = [
        "#ef4444", "#f97316", "#eab308", "#22c55e",
        "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    ];
    PALETTE[random_u64() as usize % PALETTE.len()].to_string()
}
