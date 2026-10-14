interface TicketCardProps {
  id: string;
  title: string;
  priority: 'low' | 'medium' | 'high';
  status: string;
}

export function TicketCard({ id, title, priority, status }: TicketCardProps) {
  const priorityColors = {
    low: 'bg-green-100 text-green-800',
    medium: 'bg-yellow-100 text-yellow-800',
    high: 'bg-red-100 text-red-800',
  };

  return (
    <div className="p-4 border border-gray-200 rounded-lg shadow-sm bg-white hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs font-mono text-gray-400">#{id}</span>
        <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${priorityColors[priority]}`}>
          {priority}
        </span>
      </div>
      <h3 className="text-base font-semibold text-gray-900 mb-1">{title}</h3>
      <div className="flex items-center text-xs text-gray-500 mt-2">
        <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mr-1.5"></span>
        {status}
      </div>
    </div>
  );
}

export default TicketCard;
