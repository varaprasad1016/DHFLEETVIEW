import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { getModuleAccess } from './driverApp';

// One lookup per signed-in user, shared by every component that asks.
let lookup = null;

// Whether the signed-in user can use the compliance tools: administrators and
// managers always; standard users when the super administrator has ticked at
// least one compliance module for them (Settings > Users > Permissions).
// Null-safe: the session user loads asynchronously.
const useComplianceAccess = () => {
  const userId = useSelector((state) => state.session.user?.id);
  const manager = useSelector((state) =>
    Boolean(state.session.user?.administrator || (state.session.user?.userLimit || 0) !== 0),
  );
  const [access, setAccess] = useState(manager);

  useEffect(() => {
    if (userId == null || manager) {
      setAccess(manager);
      return undefined;
    }
    let cancelled = false;
    if (!lookup || lookup.userId !== userId) {
      lookup = { userId, promise: getModuleAccess() };
    }
    lookup.promise.then((result) => {
      if (!cancelled) {
        setAccess(Boolean(result && Object.values(result.enabled || {}).some(Boolean)));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [userId, manager]);

  return access;
};

export default useComplianceAccess;
