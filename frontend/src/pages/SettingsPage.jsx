import { Settings } from "lucide-react";

/**
 * Settings & Permissions
 *
 * TODO:
 * - Profile settings
 * - Family group management
 * - Permission matrix
 * - Notification preferences
 * - Data export
 * - API key configuration (Gemini)
 * - Privacy & security settings
 */

export default function SettingsPage() {
  return (
    <div className="page">
      <h2>Settings</h2>
      <div className="card">
        <Settings size={48} />
        <p className="placeholder">Settings & permissions configuration coming soon.</p>
      </div>
    </div>
  );
}
