import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { resendVerification } from "../services/api";

/** Shown until the user confirms their email. Unconfirmed accounts can't be given access to someone else's records. */
export default function VerifyBanner() {
  const { user, reloadUser } = useAuth();
  const [msg, setMsg] = useState("");
  if (!user || user.email_verified) return null;

  const resend = async () => {
    try {
      const { data } = await resendVerification();
      if (data.already_verified) reloadUser();
      else setMsg("Sent. Check your inbox.");
    } catch (e) {
      setMsg(e.response?.status === 429 ? "Please wait a minute before asking again." : "Could not send. Try again later.");
    }
  };

  return (
    <div className="verify-banner" role="status">
      <span>Confirm your email ({user.email}) so family and doctors can share records with you.</span>
      <button className="btn btn-outline" onClick={resend}>Resend email</button>
      <button className="link-btn" onClick={reloadUser}>I have confirmed it</button>
      {msg && <span>{msg}</span>}
    </div>
  );
}
