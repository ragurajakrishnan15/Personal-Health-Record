import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

/** The Add menu links to "/page?add=1": open that page's form, then tidy the address so Back behaves normally. */
export default function useAddParam(open) {
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    if (!params.has("add")) return;
    open();
    setParams({}, { replace: true });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
}
