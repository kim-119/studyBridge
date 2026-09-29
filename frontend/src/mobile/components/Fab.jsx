import React from 'react';
import { Plus } from 'lucide-react';

export default function Fab({ label, onClick, icon = <Plus size={24} /> }) {
  return (
    <button type="button" className="mobile-fab" aria-label={label} onClick={onClick}>
      {icon}
    </button>
  );
}
