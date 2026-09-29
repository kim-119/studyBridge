import { reviewNoteService } from '../../services/api';

export class ReviewNoteListError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ReviewNoteListError';
  }
}

export async function fetchReviewNotes() {
  const result = await reviewNoteService.listReviewNotes();

  if (!result.ok) {
    throw new ReviewNoteListError(result.error);
  }

  return result.items;
}
