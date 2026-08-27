use std::fs;
use std::io::ErrorKind;
use std::path::PathBuf;

use tauri::{AppHandle, Manager};

const STATE_FILE: &str = "desktop-extension-announcements-v1";
const MAX_SEEN_ANNOUNCEMENTS: usize = 200;

fn state_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|directory| directory.join(STATE_FILE))
        .map_err(|error| format!("无法解析桌面公告状态目录: {error}"))
}

fn normalize_seen_keys(keys: Vec<String>) -> Vec<String> {
    let mut ordered = Vec::new();
    for key in keys {
        if key.is_empty() {
            continue;
        }
        if let Some(index) = ordered.iter().position(|item| item == &key) {
            ordered.remove(index);
        }
        ordered.push(key);
    }
    let excess = ordered.len().saturating_sub(MAX_SEEN_ANNOUNCEMENTS);
    if excess > 0 {
        ordered.drain(0..excess);
    }
    ordered
}

fn parse_seen_keys(raw: &str) -> Vec<String> {
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Array(items)) => normalize_seen_keys(
            items
                .into_iter()
                .filter_map(|item| match item {
                    serde_json::Value::String(value) => Some(value),
                    _ => None,
                })
                .collect(),
        ),
        _ => Vec::new(),
    }
}

#[tauri::command]
pub fn get_desktop_announcement_state(app: AppHandle) -> Result<Vec<String>, String> {
    let path = state_path(&app)?;
    match fs::read_to_string(&path) {
        Ok(raw) => Ok(parse_seen_keys(&raw)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(format!("无法读取桌面公告状态: {error}")),
    }
}

#[tauri::command]
pub fn set_desktop_announcement_state(app: AppHandle, keys: Vec<String>) -> Result<(), String> {
    let keys = normalize_seen_keys(keys);
    let path = state_path(&app)?;
    let directory = path
        .parent()
        .ok_or_else(|| "无法解析桌面公告状态目录".to_string())?;
    fs::create_dir_all(directory).map_err(|error| format!("无法创建桌面公告状态目录: {error}"))?;
    let payload = serde_json::to_string(&keys)
        .map_err(|error| format!("无法序列化桌面公告状态: {error}"))?;
    fs::write(path, payload).map_err(|error| format!("无法保存桌面公告状态: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drops_empty_keys_and_moves_duplicates_to_the_end() {
        assert_eq!(
            normalize_seen_keys(vec![
                "public-api:notice-1".to_string(),
                String::new(),
                "public-api:notice-2".to_string(),
                "public-api:notice-1".to_string(),
            ]),
            vec![
                "public-api:notice-2".to_string(),
                "public-api:notice-1".to_string(),
            ]
        );
    }

    #[test]
    fn keeps_only_the_most_recent_seen_keys() {
        let keys = (0..=MAX_SEEN_ANNOUNCEMENTS)
            .map(|index| format!("public-api:notice-{index}"))
            .collect::<Vec<_>>();

        let normalized = normalize_seen_keys(keys);

        assert_eq!(normalized.len(), MAX_SEEN_ANNOUNCEMENTS);
        assert_eq!(normalized.first().unwrap(), "public-api:notice-1");
        assert_eq!(
            normalized.last().unwrap(),
            &format!("public-api:notice-{MAX_SEEN_ANNOUNCEMENTS}")
        );
    }

    #[test]
    fn invalid_or_non_array_state_fails_open() {
        assert!(parse_seen_keys("").is_empty());
        assert!(parse_seen_keys("{").is_empty());
        assert!(parse_seen_keys("{\"keys\":[]}").is_empty());
        assert_eq!(
            parse_seen_keys(r#"["public-api:notice-1", 2, null, ""]"#),
            vec!["public-api:notice-1".to_string()]
        );
    }
}
